from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from sqlalchemy import exists, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..browser.context import persistent_context
from ..browser.fixture_search_pages import DETAIL_TARGET
from ..browser.fixture_submit import FixtureSubmitPage, SubmitResult
from ..browser.safe_stop import SafeStop, StopReason
from ..config import ScoringSettings, load_browser_settings, load_scoring_settings
from ..models.application import Application
from ..models.automation_guard import AutomationGuard
from ..models.job import Job
from ..models.task import Task
from .applications import finish_auto_attempt
from .review import ProgressCallback, StopCallback


@dataclass(frozen=True)
class Candidate:
    job_id: int
    identity_key: str
    title: str
    priority: int
    score: float

    def summary(self) -> dict:
        return {"job_id": self.job_id, "title": self.title, "priority": self.priority, "score": self.score}


@dataclass
class AutoSummary:
    status: str
    stop_reason: str | None
    progress: dict


class AutoRecoveryRequired(RuntimeError):
    def __init__(self, summary: AutoSummary):
        self.summary = summary


def _verified_identity(job: Job) -> bool:
    if job.source_job_id:
        return job.identity_key == f"{job.source}:{job.source_job_id}"
    try:
        address = urlsplit(job.source_url or "")
    except ValueError:
        return False
    target = f"{address.path}?{address.query}"
    return (
        address.scheme == "http"
        and address.hostname == "127.0.0.1"
        and not address.fragment
        and DETAIL_TARGET.fullmatch(target) is not None
        and job.identity_key == f"url:{sha256(target.encode('utf-8')).hexdigest()}"
    )


def exclusion_reason(
    job: Job, provider: str, scoring: ScoringSettings, blocking: str | None, has_failed: bool,
) -> str | None:
    if job.source != provider:
        return "SOURCE_MISMATCH"
    if blocking in {"succeeded", "sending", "uncertain"}:
        return f"APPLICATION_{blocking.upper()}"
    if job.jd_state != "complete" or not (job.jd_text or "").strip():
        return "JD_INCOMPLETE"
    if not _verified_identity(job):
        return "IDENTITY_UNVERIFIED"
    if job.availability == "inactive":
        return "JOB_INACTIVE"
    if not job.recommended:
        return "NOT_RECOMMENDED"
    if job.scoring_version != scoring.version or job.priority not in {1, 2, 3, 4} or job.score is None:
        return "SCORING_STALE"
    if job.score < scoring.document["scoring"]["recommendation_threshold"]:
        return "SCORE_BELOW_THRESHOLD"
    if has_failed and blocking != "pending":
        return "FAILED_NEEDS_REQUEUE"
    return None


def plan_candidates(
    engine: Engine, provider: str, scoring: ScoringSettings, job_ids: list[int], limit: int,
) -> tuple[list[Candidate], list[dict]]:
    failed = exists().where(Application.job_id == Job.id, Application.status == "failed").correlate(Job)
    with Session(engine) as session:
        rows = session.execute(
            select(Job, Application.status, failed)
            .outerjoin(Application, Application.blocking_job_id == Job.id)
            .where(Job.id.in_(job_ids))
            .order_by(Job.priority.asc(), Job.score.desc(), Job.id.desc())
        ).all()

    candidates = []
    skipped = []
    found = set()
    for job, blocking, has_failed in rows:
        found.add(job.id)
        reason = exclusion_reason(job, provider, scoring, blocking, has_failed)
        if reason is None and len(candidates) >= limit:
            reason = "MAX_JOBS"
        if reason:
            skipped.append({"job_id": job.id, "reason": reason})
        else:
            candidates.append(Candidate(job.id, job.identity_key, job.title, job.priority, float(job.score)))
    skipped.extend({"job_id": job_id, "reason": "JOB_NOT_FOUND"} for job_id in job_ids if job_id not in found)
    return candidates, skipped


def _reserve_attempt(
    engine: Engine, task_id: int, candidate: Candidate, scoring: ScoringSettings,
) -> tuple[int | None, str | None]:
    if load_scoring_settings().document != scoring.document:
        return None, "SCORING_CHANGED"
    with Session(engine) as session, session.begin():
        guard = session.get(AutomationGuard, "fixture", with_for_update=True)
        if guard is None or (guard.blocked_at is not None and guard.acknowledged_at is None):
            return None, "PROVIDER_PAUSED"
        task = session.get(Task, task_id, with_for_update=True)
        if task is None or task.status != "running":
            return None, "USER_STOPPED"
        job = session.get(Job, candidate.job_id, with_for_update=True)
        if job is None:
            return None, "JOB_NOT_FOUND"
        if job.identity_key != candidate.identity_key:
            return None, "IDENTITY_CHANGED"
        blocking = session.scalar(
            select(Application).where(Application.blocking_job_id == job.id).with_for_update()
        )
        has_failed = session.scalar(select(exists().where(Application.job_id == job.id, Application.status == "failed")))
        reason = exclusion_reason(job, task.provider, scoring, blocking.status if blocking else None, has_failed)
        if reason:
            return None, reason
        attempt = blocking or Application(job_id=job.id)
        attempt.task_id = task_id
        attempt.origin = "auto"
        attempt.status = "sending"
        attempt.started_at = datetime.now(UTC).replace(tzinfo=None)
        attempt.resolved_at = None
        attempt.result_code = None
        attempt.evidence_summary = None
        session.add(attempt)
        session.flush()
        return attempt.id, None


def _attempt(
    page: FixtureSubmitPage, candidate: Candidate, should_stop: StopCallback,
) -> tuple[SubmitResult, str | None]:
    previous_calls = page.submit_calls
    if should_stop():
        return SubmitResult("failed", "SUBMIT_CANCELLED", "本地样例：提交前收到停止请求"), "USER_STOPPED"
    try:
        page.open(candidate.job_id, candidate.identity_key)
        result = page.submit(should_stop)
    except (SafeStop, PlaywrightError) as error:
        action_attempted = page.submit_calls != previous_calls
        reason = error.reason.value if isinstance(error, SafeStop) else (
            "SUBMIT_UNCERTAIN" if action_attempted else StopReason.PAGE_UNRECOGNIZED.value
        )
        evidence = "本地样例：动作尝试后无法核对当前职位" if action_attempted else "本地样例：安全停止发生在提交动作之前"
        return SubmitResult("uncertain" if action_attempted else "failed", reason, evidence), reason
    if result.status == "uncertain":
        return result, "SUBMIT_UNCERTAIN"
    if result.code == "SUBMIT_CANCELLED":
        return result, "USER_STOPPED"
    return result, None


def _simulate(
    engine: Engine,
    task_id: int,
    candidates: list[Candidate],
    scoring: ScoringSettings,
    state: dict,
    cases: dict[int, str],
    progress: ProgressCallback,
    should_stop: StopCallback,
    latch_risk: Callable[[str], None],
) -> AutoSummary:
    browser = load_browser_settings()
    browser.profile_root.mkdir(parents=True, exist_ok=True)
    stop_reason = None
    with TemporaryDirectory(prefix=f"auto-{task_id}-", dir=browser.profile_root) as directory:
        with persistent_context(browser, Path(directory)) as context:
            page = FixtureSubmitPage(context, cases)
            for candidate in candidates:
                if should_stop():
                    stop_reason = "USER_STOPPED"
                    break
                attempt_id, reason = _reserve_attempt(engine, task_id, candidate, scoring)
                if reason in {"SCORING_CHANGED", "PROVIDER_PAUSED", "USER_STOPPED"}:
                    stop_reason = reason
                    break
                if attempt_id is None:
                    state["skipped_jobs"].append({"job_id": candidate.job_id, "reason": reason})
                    state["skipped"][reason] = state["skipped"].get(reason, 0) + 1
                    progress("submitting", state)
                    continue

                result, stop_reason = _attempt(page, candidate, should_stop)
                state["browser_submit_calls"] = page.submit_calls
                try:
                    finish_auto_attempt(engine, attempt_id, task_id, result)
                    state[result.status] += 1
                    if stop_reason and stop_reason != "USER_STOPPED":
                        latch_risk(stop_reason)
                except SQLAlchemyError as error:
                    reason = stop_reason if stop_reason and stop_reason != "USER_STOPPED" else "SUBMIT_UNCERTAIN"
                    raise AutoRecoveryRequired(AutoSummary("stopped", reason, state)) from error
                progress("submitting", state)
                if stop_reason:
                    break
    if stop_reason:
        return AutoSummary("stopped", stop_reason, state)
    return AutoSummary("succeeded", None, state)


def run_auto(
    engine: Engine,
    task_id: int,
    *,
    provider: str,
    params: dict,
    scoring: ScoringSettings,
    progress: ProgressCallback,
    should_stop: StopCallback,
    cases: dict[int, str] | None,
    latch_risk: Callable[[str], None],
) -> AutoSummary:
    progress("planning", {"browser_submit_calls": 0})
    if load_scoring_settings().document != scoring.document:
        return AutoSummary("stopped", "SCORING_CHANGED", {"browser_submit_calls": 0})
    candidates, skipped = plan_candidates(engine, provider, scoring, params["job_ids"], params["max_jobs"])
    state = {
        "browser_submit_calls": 0,
        "plan": [candidate.summary() for candidate in candidates],
        "skipped_jobs": skipped,
        "skipped": dict(Counter(item["reason"] for item in skipped)),
    }
    if should_stop():
        return AutoSummary("stopped", "USER_STOPPED", state)
    if params["dry_run"] or not candidates:
        return AutoSummary("succeeded", None, state)
    if cases is None:
        raise ValueError("Isolated fixture simulation is disabled.")
    state.update(succeeded=0, failed=0, uncertain=0)
    progress("submitting", state)
    return _simulate(engine, task_id, candidates, scoring, state, cases, progress, should_stop, latch_risk)
