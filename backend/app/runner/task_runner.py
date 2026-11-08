from datetime import datetime, timezone
import logging
from threading import Event, Thread

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..config import ScoringSettings
from ..models.automation_guard import AutomationGuard
from ..models.task import Task
from ..services.review import ReviewSummary, run_review
from .instance_lock import acquire_task_runner_lock, release_task_runner_lock


logger = logging.getLogger(__name__)
TERMINAL = {"succeeded", "failed", "stopped", "interrupted"}
RISK_STOP_CODES = {
    "CAPTCHA_REQUIRED",
    "SECURITY_CHECK",
    "RATE_LIMITED",
    "ACCOUNT_ABNORMAL",
    "LOGIN_REQUIRED",
    "PAGE_UNRECOGNIZED",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TaskRunner:
    """One locked process-wide worker with the MySQL active-slot index as a second guard."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self._shutdown = Event()
        self._wakeup = Event()
        self._thread: Thread | None = None
        self._active_task_id: int | None = None
        self._instance_lock = None

    def recover_after_restart(self) -> int:
        recovered = 0
        now = _utcnow()
        with Session(self.engine) as session, session.begin():
            stale_tasks = session.scalars(
                select(Task)
                .where(Task.status.in_(("queued", "running", "stop_requested")))
                .with_for_update()
            ).all()
            for task in stale_tasks:
                prior_status = task.status
                task.status = "interrupted"
                task.phase = "interrupted"
                task.stop_reason = "PROCESS_RESTART"
                task.error_code = "PROCESS_RESTART"
                task.finished_at = now
                task.progress_json = {**(task.progress_json or {}), "recovery": "interrupted_after_restart"}
                guard = session.get(AutomationGuard, "boss") if task.provider == "boss" and prior_status in {"running", "stop_requested"} else None
                if guard is not None:
                    guard.blocked_at = now
                    guard.reason_code = "PROCESS_RESTART"
                    guard.task_id = task.id
                    guard.acknowledged_at = None
                recovered += 1
        return recovered

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._instance_lock = acquire_task_runner_lock()
        try:
            try:
                self.recover_after_restart()
            except SQLAlchemyError as error:
                logger.warning("Task recovery deferred exception=%s", error.__class__.__name__)
            self._shutdown.clear()
            self._thread = Thread(target=self._serve, name="boss-review-worker", daemon=True)
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

    def _claim_next(self) -> tuple[int, dict, dict] | None:
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
            return task.id, dict(task.params_json), dict(task.rule_snapshot or {})

    def _finish(self, task_id: int, summary: ReviewSummary) -> None:
        now = _utcnow()
        with Session(self.engine) as session, session.begin():
            task = session.scalar(select(Task).where(Task.id == task_id).with_for_update())
            if task is None or task.status in TERMINAL:
                return
            stopped_by_user = task.status == "stop_requested" or summary.stop_reason in {"USER_STOPPED", "SERVER_SHUTDOWN"}
            task.status = "stopped" if summary.status == "stopped" or stopped_by_user else summary.status
            task.phase = task.status
            if summary.stop_reason:
                task.stop_reason = summary.stop_reason
            elif stopped_by_user:
                task.stop_reason = "USER_STOPPED" if task.stop_reason == "USER_REQUESTED" else task.stop_reason
            else:
                task.stop_reason = None
            task.error_code = None
            task.progress_json = summary.progress
            task.finished_at = now
            if task.stop_reason in RISK_STOP_CODES:
                guard = session.get(AutomationGuard, task.provider)
                if guard is not None:
                    guard.blocked_at = now
                    guard.reason_code = task.stop_reason
                    guard.task_id = task.id
                    guard.acknowledged_at = None

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

    def _run_task(self, task_id: int, params: dict, rule_snapshot: dict) -> None:
        try:
            version = rule_snapshot.get("version")
            if not version:
                raise ValueError("missing rule snapshot")
            summary = run_review(
                self.engine,
                task_id,
                params=params,
                scoring_settings=ScoringSettings(version=version, document=rule_snapshot),
                progress=lambda phase, data: self.update_progress(task_id, phase, data),
                should_stop=lambda: self.is_stop_requested(task_id),
            )
            self._finish(task_id, summary)
        except Exception as error:
            if error.__class__.__name__ == "BrowserBusy":
                code = "BROWSER_BUSY"
            elif isinstance(error, SQLAlchemyError):
                code = "DATABASE_WRITE_FAILED"
            else:
                code = "REVIEW_FAILED"
            logger.warning("Review task failed task_id=%s code=%s exception=%s", task_id, code, error.__class__.__name__)
            try:
                self._fail(task_id, code)
            except Exception as finish_error:
                logger.warning("Could not persist failed state task_id=%s exception=%s", task_id, finish_error.__class__.__name__)

    def _serve(self) -> None:
        while not self._shutdown.is_set():
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
            task_id, params, rules = claimed
            self._active_task_id = task_id
            self._run_task(task_id, params, rules)
            self._active_task_id = None
