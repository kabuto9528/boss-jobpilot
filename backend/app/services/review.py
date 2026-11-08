from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from sqlalchemy import text
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..browser.context import persistent_context
from ..browser.fixture import fixture_site
from ..browser.search_read import SearchResult, read_fixture_search
from ..config import BrowserSettings, ScoringSettings, load_browser_settings
from ..models.job import Job
from ..services.parser import NormalizedJob
from ..services.scoring import ScoringResult, score_job


ProgressCallback = Callable[[str, dict], None]
StopCallback = Callable[[], bool]


@dataclass
class ReviewSummary:
    status: str
    stop_reason: str | None
    progress: dict
    browser_submit_calls: int = 0


def _persist_scored_job(engine: Engine, task_id: int, job: NormalizedJob, result: ScoringResult) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    statement = insert(Job).values(
        source=job.source,
        source_job_id=job.source_job_id,
        identity_key=job.identity_key,
        source_url=job.source_url,
        title=job.title,
        company=job.company,
        city=job.city,
        salary_text=job.salary_text,
        experience_text=job.experience_text,
        jd_text=job.jd_text,
        jd_state=job.jd_state,
        availability=job.availability,
        job_type=result.job_type,
        priority=result.priority,
        score=Decimal(result.score),
        recommended=result.recommended,
        score_reasons={
            "reasons": list(result.reasons),
            "evidence": [asdict(item) for item in result.evidence],
            "hard_exclusions": list(result.hard_exclusions),
        },
        scoring_version=result.scoring_version,
        last_task_id=task_id,
        first_seen_at=now,
        last_seen_at=now,
    )
    statement = statement.on_duplicate_key_update(
        source_job_id=statement.inserted.source_job_id,
        source_url=statement.inserted.source_url,
        title=statement.inserted.title,
        company=statement.inserted.company,
        city=statement.inserted.city,
        salary_text=statement.inserted.salary_text,
        experience_text=statement.inserted.experience_text,
        jd_text=statement.inserted.jd_text,
        jd_state=statement.inserted.jd_state,
        availability=statement.inserted.availability,
        job_type=statement.inserted.job_type,
        priority=statement.inserted.priority,
        score=statement.inserted.score,
        recommended=statement.inserted.recommended,
        score_reasons=statement.inserted.score_reasons,
        scoring_version=statement.inserted.scoring_version,
        last_task_id=task_id,
        last_seen_at=text("CURRENT_TIMESTAMP(6)"),
    )
    # Keep each upsert short so the task status and other API reads remain available.
    with Session(engine) as session, session.begin():
        session.execute(statement)


def run_review(
    engine: Engine,
    task_id: int,
    *,
    params: dict,
    scoring_settings: ScoringSettings,
    progress: ProgressCallback,
    should_stop: StopCallback,
    browser_settings: BrowserSettings | None = None,
) -> ReviewSummary:
    browser_settings = browser_settings or load_browser_settings()
    progress_state = {
        "keyword_count": len(params["keywords"]),
        "keyword_index": 0,
        "pages_attempted": 0,
        "details_attempted": 0,
        "jobs_found": 0,
        "jobs_saved": 0,
        "duplicates": 0,
        "skipped": {},
        "browser_submit_calls": 0,
    }
    seen_identities: set[str] = set()
    final_stop_reason: str | None = None

    browser_settings.profile_root.mkdir(parents=True, exist_ok=True)
    for index, keyword in enumerate(params["keywords"], start=1):
        if should_stop():
            final_stop_reason = "USER_STOPPED"
            break
        progress_state["keyword_index"] = index
        progress("reading", dict(progress_state))

        def save_job(job: NormalizedJob) -> None:
            if job.identity_key in seen_identities:
                progress_state["duplicates"] += 1
                return
            seen_identities.add(job.identity_key)
            result = score_job(job, scoring_settings)
            progress_state["jobs_found"] += 1
            progress("writing", dict(progress_state))
            _persist_scored_job(engine, task_id, job, result)
            progress_state["jobs_saved"] += 1
            progress("writing", dict(progress_state))

        base_pages = progress_state["pages_attempted"]
        base_details = progress_state["details_attempted"]

        def search_progress(phase: str, values: dict) -> None:
            view = dict(progress_state)
            view["pages_attempted"] = base_pages + values.get("pages_attempted", 0)
            view["details_attempted"] = base_details + values.get("details_attempted", 0)
            view["duplicates"] += values.get("duplicates", 0)
            view["skipped"] = {
                **progress_state["skipped"],
                **{
                    reason: progress_state["skipped"].get(reason, 0) + count
                    for reason, count in values.get("skipped", {}).items()
                },
            }
            progress(phase, view)

        write_requests: list[str] = []
        with fixture_site() as origin, TemporaryDirectory(
            prefix=f"task-{task_id}-{index}-", dir=browser_settings.profile_root
        ) as profile_directory:
            with persistent_context(browser_settings, Path(profile_directory)) as context:
                context.on(
                    "request",
                    lambda browser_request: write_requests.append(browser_request.method)
                    if browser_request.method != "GET"
                    else None,
                )
                result: SearchResult = read_fixture_search(
                    context,
                    origin,
                    keyword=keyword,
                    max_pages=params["max_pages"],
                    max_jobs=params["max_jobs"],
                    should_stop=should_stop,
                    on_job=save_job,
                    on_progress=search_progress,
                )

        progress_state["browser_submit_calls"] += len(write_requests)
        progress_state["pages_attempted"] += result.pages_attempted
        progress_state["details_attempted"] += result.details_attempted
        progress_state["duplicates"] += result.duplicates
        for reason, count in result.skipped.items():
            progress_state["skipped"][reason] = progress_state["skipped"].get(reason, 0) + count
        if result.stop_reason not in {"exhausted", "empty_results", "max_pages", "max_jobs"}:
            final_stop_reason = result.stop_reason
            break

    if final_stop_reason is None and should_stop():
        final_stop_reason = "USER_STOPPED"
    if final_stop_reason:
        return ReviewSummary("stopped", final_stop_reason, progress_state, progress_state["browser_submit_calls"])
    return ReviewSummary("succeeded", None, progress_state, progress_state["browser_submit_calls"])
