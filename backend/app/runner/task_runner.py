from datetime import datetime, timezone
import logging
from threading import Event, Thread

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..config import ScoringSettings, load_browser_settings
from ..models.application import Application
from ..models.automation_guard import AutomationGuard
from ..models.job import Job
from ..models.task import Task
from ..services.applications import mark_auto_attempt_uncertain
from ..services.auto import AutoRecoveryRequired, AutoSummary, run_auto
from ..services.management import latch_guard, lock_control_guards
from ..services.review import ReviewSummary, run_review
from .instance_lock import acquire_task_runner_lock, release_task_runner_lock
from .profile_lock import BrowserBusy, browser_lock, ensure_profiles_idle


logger = logging.getLogger(__name__)
TERMINAL = {"succeeded", "failed", "stopped", "interrupted"}
RISK_STOP_CODES = {
    "CAPTCHA_REQUIRED",
    "SECURITY_CHECK",
    "RATE_LIMITED",
    "ACCOUNT_ABNORMAL",
    "LOGIN_REQUIRED",
    "PAGE_UNRECOGNIZED",
    "SUBMIT_UNCERTAIN",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TaskRunner:
    """One locked process-wide worker with the MySQL active-slot index as a second guard."""

    def __init__(self, engine: Engine, *, fixture_submit_cases: dict[int, str] | None = None):
        self.engine = engine
        self._fixture_submit_cases = None if fixture_submit_cases is None else dict(fixture_submit_cases)
        self.recovery_pending = True
        self._shutdown = Event()
        self._wakeup = Event()
        self._thread: Thread | None = None
        self._active_task_id: int | None = None
        self._instance_lock = None

    def recover_after_restart(self) -> int:
        now = _utcnow()
        with Session(self.engine) as session, session.begin():
            guards = lock_control_guards(session)
            stale_tasks = session.scalars(
                select(Task)
                .where(Task.status.in_(("queued", "running", "stop_requested")))
                .with_for_update()
            ).all()
            stale_auto_ids = [task.id for task in stale_tasks if task.mode == "auto"]
            outstanding = session.execute(
                select(Application, Job.source)
                .join(Job, Job.id == Application.job_id)
                .where(Application.status == "sending")
                .where((Application.origin == "auto") | Application.task_id.in_(stale_auto_ids))
                .with_for_update()
            ).all()
            if stale_tasks or outstanding:
                self._check_browser_cleanup()
            uncertain_by_task: dict[int, int] = {}
            for attempt, source in outstanding:
                mark_auto_attempt_uncertain(attempt, "PROCESS_RESTART")
                guard = guards.get(source)
                if guard is not None and (guard.blocked_at is None or guard.acknowledged_at is not None):
                    latch_guard(guard, "SUBMIT_UNCERTAIN", attempt.task_id, now)
                if attempt.task_id is not None:
                    uncertain_by_task[attempt.task_id] = uncertain_by_task.get(attempt.task_id, 0) + 1
            for task in stale_tasks:
                prior_status = task.status
                task.status = "interrupted"
                task.phase = "interrupted"
                task.stop_reason = "PROCESS_RESTART"
                task.error_code = "PROCESS_RESTART"
                task.finished_at = now
                task.progress_json = {**(task.progress_json or {}), "recovery": "interrupted_after_restart"}
                if task.id in uncertain_by_task:
                    task.progress_json["uncertain"] = task.progress_json.get("uncertain", 0) + uncertain_by_task[task.id]
                if prior_status in {"running", "stop_requested"} and (
                    task.provider == "boss" or (task.mode == "auto" and not task.dry_run)
                ):
                    guard = guards.get(task.provider)
                    if guard is not None and (guard.blocked_at is None or guard.acknowledged_at is not None):
                        latch_guard(guard, "PROCESS_RESTART", task.id, now)
        return len(stale_tasks)

    @staticmethod
    def _check_browser_cleanup() -> None:
        with browser_lock():
            ensure_profiles_idle(load_browser_settings().profile_root)

    def _recover(self) -> None:
        try:
            self.recover_after_restart()
        except (SQLAlchemyError, BrowserBusy) as error:
            logger.warning("Task recovery deferred exception=%s", error.__class__.__name__)
        else:
            self.recovery_pending = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._instance_lock = acquire_task_runner_lock()
        try:
            self._shutdown.clear()
            self.recovery_pending = True
            self._recover()
            self._thread = Thread(target=self._serve, name="boss-task-worker", daemon=True)
            self._thread.start()
        except Exception:
            release_task_runner_lock(self._instance_lock)
            self._instance_lock = None
            raise

    def stop(self, timeout: float = 10.0) -> None:
        self._shutdown.set()
        self._wakeup.set()
        task_id = self._active_task_id
        if task_id is not None:
            try:
                self.request_stop(task_id, reason="SERVER_SHUTDOWN")
            except Exception:
                logger.warning("Could not persist shutdown stop for task_id=%s", task_id)
        if self._thread:
            self._thread.join(timeout=timeout)
        if (self._thread is None or not self._thread.is_alive()) and self._instance_lock is not None:
            release_task_runner_lock(self._instance_lock)
            self._instance_lock = None

    def wake(self) -> None:
        self._wakeup.set()

    def request_stop(self, task_id: int, *, reason: str = "USER_REQUESTED") -> bool:
        with Session(self.engine) as session, session.begin():
            task = session.scalar(select(Task).where(Task.id == task_id).with_for_update())
            if task is None or task.status in TERMINAL:
                return False
            if task.status == "queued":
                task.status = "stopped"
                task.phase = "stopped"
                task.stop_reason = "USER_STOPPED" if reason == "USER_REQUESTED" else reason
                task.finished_at = _utcnow()
            elif task.status == "running":
                task.status = "stop_requested"
                task.stop_reason = reason
        self._wakeup.set()
        return True

    def is_stop_requested(self, task_id: int) -> bool:
        if self._shutdown.is_set():
            return True
        with Session(self.engine) as session:
            status = session.scalar(select(Task.status).where(Task.id == task_id))
        return status in {"stop_requested", "stopped"}

    def update_progress(self, task_id: int, phase: str, progress: dict) -> None:
        with Session(self.engine) as session, session.begin():
            task = session.scalar(select(Task).where(Task.id == task_id).with_for_update())
            if task is None or task.status in TERMINAL:
                return
            task.phase = phase
            task.progress_json = progress

    def _claim_next(self) -> tuple[int, str, str, bool, dict, dict] | None:
        with Session(self.engine) as session, session.begin():
            task = session.scalar(
                select(Task)
                .where(Task.status == "queued")
                .order_by(Task.created_at.asc(), Task.id.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if task is None:
                return None
            task.status = "running"
            task.phase = "starting"
            task.started_at = _utcnow()
            task.progress_json = task.progress_json or {
                "keyword_count": len(task.params_json.get("keywords", [])),
                "keyword_index": 0,
                "pages_attempted": 0,
                "details_attempted": 0,
                "jobs_found": 0,
                "jobs_saved": 0,
                "duplicates": 0,
                "skipped": {},
            }
            return task.id, task.mode, task.provider, task.dry_run, dict(task.params_json), dict(task.rule_snapshot or {})

    def _latch_risk(self, task_id: int, provider: str, reason: str) -> None:
        with Session(self.engine) as session, session.begin():
            guard = session.get(AutomationGuard, provider, with_for_update=True)
            latch_guard(guard, reason, task_id, _utcnow())

    def _finish(
        self, task_id: int, summary: ReviewSummary | AutoSummary, *,
        recover_sending: bool = False, error_code: str | None = None,
    ) -> None:
        now = _utcnow()
        with Session(self.engine) as session, session.begin():
            guards = lock_control_guards(session) if recover_sending or summary.stop_reason in RISK_STOP_CODES else {}
            task = session.scalar(select(Task).where(Task.id == task_id).with_for_update())
            if task is None or task.status in TERMINAL:
                return
            reason = summary.stop_reason
            state = dict(summary.progress or task.progress_json or {})
            guard = guards.get(task.provider)
            if recover_sending:
                attempts = session.scalars(
                    select(Application).where(Application.task_id == task_id, Application.status == "sending").with_for_update()
                ).all()
                if attempts:
                    reason = reason or "SUBMIT_UNCERTAIN"
                    for attempt in attempts:
                        mark_auto_attempt_uncertain(attempt, reason)
                    state["uncertain"] = state.get("uncertain", 0) + len(attempts)
                if guard is not None and guard.task_id == task_id and guard.acknowledged_at is None:
                    reason = guard.reason_code or reason
            stopped_by_user = task.status == "stop_requested" or reason in {"USER_STOPPED", "SERVER_SHUTDOWN"}
            task.status = "stopped" if summary.status == "stopped" or stopped_by_user or reason in RISK_STOP_CODES else summary.status
            task.phase = task.status
            if reason:
                task.stop_reason = reason
            elif stopped_by_user:
                task.stop_reason = "USER_STOPPED" if task.stop_reason == "USER_REQUESTED" else task.stop_reason
            else:
                task.stop_reason = None
            task.error_code = error_code
            task.progress_json = state
            task.finished_at = now
            if task.stop_reason in RISK_STOP_CODES:
                latch_guard(guard, task.stop_reason, task.id, now)

    def _settle_auto(self, task_id: int, summary: AutoSummary, code: str) -> None:
        # The active slot stays reserved until cleanup and the result can be persisted.
        # Only the ledger finalization is retried, never the browser operation.
        while not self._shutdown.is_set():
            try:
                self._check_browser_cleanup()
                self._finish(task_id, summary, recover_sending=True, error_code=code)
                return
            except (SQLAlchemyError, BrowserBusy):
                self._shutdown.wait(0.5)

    def _fail(self, task_id: int, error_code: str) -> None:
        with Session(self.engine) as session, session.begin():
            task = session.scalar(select(Task).where(Task.id == task_id).with_for_update())
            if task is None or task.status in TERMINAL:
                return
            task.status = "failed"
            task.phase = "failed"
            task.error_code = error_code
            task.finished_at = _utcnow()
            task.progress_json = task.progress_json or {}

    def _run_task(self, task_id: int, mode: str, provider: str, dry_run: bool, params: dict, rule_snapshot: dict) -> None:
        simulation = mode == "auto" and not dry_run
        try:
            if provider != "fixture":
                self._fail(task_id, "AUTO_DISABLED" if mode == "auto" else "PROVIDER_DISABLED")
                return
            version = rule_snapshot.get("version")
            if not version:
                raise ValueError("missing rule snapshot")
            scoring = ScoringSettings(version=version, document=rule_snapshot)

            def progress(phase, data):
                self.update_progress(task_id, phase, data)

            def should_stop():
                return self.is_stop_requested(task_id)

            if mode == "auto":
                confirmed_simulation = (
                    self._fixture_submit_cases is not None and params.get("confirm_simulation") is True
                    and params.get("confirm_live") is False
                )
                if params.get("dry_run") is not dry_run or (simulation and not confirmed_simulation):
                    self._fail(task_id, "AUTO_DISABLED")
                    return
                summary = run_auto(
                    self.engine, task_id, provider=provider, params=params, scoring=scoring,
                    progress=progress, should_stop=should_stop,
                    cases=self._fixture_submit_cases,
                    latch_risk=lambda reason: self._latch_risk(task_id, provider, reason),
                )
            else:
                summary = run_review(
                    self.engine, task_id, params=params, scoring_settings=scoring,
                    progress=progress, should_stop=should_stop,
                )
            self._finish(task_id, summary)
        except AutoRecoveryRequired as error:
            logger.warning("Auto task requires ledger recovery task_id=%s", task_id)
            self._settle_auto(task_id, error.summary, "DATABASE_WRITE_FAILED")
        except Exception as error:
            if isinstance(error, BrowserBusy):
                code = "BROWSER_BUSY"
            elif isinstance(error, SQLAlchemyError):
                code = "DATABASE_WRITE_FAILED"
            else:
                code = "AUTO_FAILED" if mode == "auto" else "REVIEW_FAILED"
            logger.warning("Task failed task_id=%s code=%s exception=%s", task_id, code, error.__class__.__name__)
            if simulation and not isinstance(error, BrowserBusy):
                self._settle_auto(task_id, AutoSummary("failed", None, {}), code)
                return
            try:
                self._fail(task_id, code)
            except Exception as finish_error:
                logger.warning("Could not persist failed state task_id=%s exception=%s", task_id, finish_error.__class__.__name__)

    def _serve(self) -> None:
        while not self._shutdown.is_set():
            if self.recovery_pending:
                self._shutdown.wait(0.5)
                if not self._shutdown.is_set():
                    self._recover()
                continue
            try:
                claimed = self._claim_next()
            except Exception as error:
                logger.warning("Task worker could not claim task exception=%s", error.__class__.__name__)
                self._wakeup.wait(0.5)
                self._wakeup.clear()
                continue
            if claimed is None:
                self._wakeup.wait(0.25)
                self._wakeup.clear()
                continue
            task_id, mode, provider, dry_run, params, rules = claimed
            self._active_task_id = task_id
            self._run_task(task_id, mode, provider, dry_run, params, rules)
            self._active_task_id = None
