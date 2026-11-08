from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy.orm import Session

from ..config import load_app_document, load_browser_settings, load_scoring_settings
from ..models.automation_guard import AutomationGuard
from ..schemas.tasks import MAX_AUTO_SELECTION, MAX_JOBS, MAX_KEYWORDS, MAX_PAGES, ReviewTaskParams
from ..services.management import SOURCES, Source, active_task, lock_control_guards, utc_timestamp
from .applications import Database
from .management_access import require_local_control


router = APIRouter(tags=["settings"])


class GuardStatus(BaseModel):
    provider: Source
    state: Literal["clear", "blocked", "unavailable"]
    reason_code: str | None = None
    task_id: int | None = None
    blocked_at: datetime | None = None
    acknowledged_at: datetime | None = None


class GuardAcknowledgement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: StrictBool
    blocked_at: datetime


def guard_status(provider: Source, row: AutomationGuard | None) -> GuardStatus:
    if row is None:
        return GuardStatus(provider=provider, state="unavailable")
    return GuardStatus(
        provider=provider, state="blocked" if row.blocked_at is not None and row.acknowledged_at is None else "clear",
        reason_code=row.reason_code, task_id=row.task_id, blocked_at=utc_timestamp(row.blocked_at),
        acknowledged_at=utc_timestamp(row.acknowledged_at),
    )


@router.get("/api/settings")
def read_settings(engine: Database, request: Request) -> dict:
    try:
        document = load_app_document()
        search = document["search"]
        defaults = ReviewTaskParams.model_validate({key: search[key] for key in ("keywords", "city", "max_pages", "max_jobs")})
        poll_interval = document["tasks"]["poll_interval_ms"]
        if type(poll_interval) is not int or not 250 <= poll_interval <= 60000:
            raise ValueError("invalid polling interval")
        browser = load_browser_settings()
        rules = load_scoring_settings()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(503, detail={"code": "SETTINGS_UNAVAILABLE", "message": "本地配置不可用，请检查 YAML 文件"}) from None

    scoring = rules.document
    experience = scoring["experience"]
    # Project selected fields at every level; never return raw YAML or process settings.
    scoring_view = {
        "version": rules.version,
        **{key: scoring["scoring"][key] for key in ("base", "minimum", "maximum", "recommendation_threshold")},
        "type_priority": {key: scoring["type_priority"][key] for key in ("internship", "campus", "junior", "social")},
        "directions_maximum_rules": scoring["directions"]["maximum_rules"],
        "recruitment_maximum_points": scoring["recruitment"]["maximum_points"],
        "skills_maximum_points": scoring["skills"]["maximum_points"],
        **{
            key: [{"label": row["label"], "points": row["points"]} for row in scoring[key]["rules"]]
            for key in ("directions", "recruitment", "skills")
        },
        "experience": {
            "hard_exclude_min_years": experience["hard_exclude_min_years"],
            "senior_deduction": experience["senior"]["deduction"],
            "thresholds": [{"years": row["years"], "deduction": row["deduction"]} for row in experience["thresholds"]],
        },
        "hard_exclusions": [row["label"] for row in scoring["hard_exclusions"]],
    }
    with Session(engine) as session:
        guards = [guard_status(source, session.get(AutomationGuard, source)) for source in SOURCES]
        is_busy = active_task(session) is not None
    return {
        "search": {"provider": "fixture", **defaults.model_dump()},
        "review_limits": {"max_keywords": MAX_KEYWORDS, "max_pages": MAX_PAGES, "max_jobs": MAX_JOBS},
        "auto_limits": {"max_selection": MAX_AUTO_SELECTION, "max_jobs": MAX_JOBS},
        "poll_interval_ms": poll_interval,
        "browser_timeout_ms": browser.timeout_ms,
        "scoring": scoring_view,
        "capabilities": {
            "fixture": {
                "review_enabled": True, "auto_preview_enabled": True,
                "auto_enabled": request.app.state.fixture_simulation_enabled,
                "login": {"status": "not_required", "checked_at": None},
            },
            "boss": {
                "review_enabled": False, "auto_preview_enabled": False, "auto_enabled": False,
                "login": {"status": "not_checked", "checked_at": None},
            },
        },
        "guards": guards,
        "task_busy": is_busy,
    }


@router.post("/api/automation-guard/{provider}/acknowledge", response_model=GuardStatus, dependencies=[Depends(require_local_control)])
def acknowledge(provider: Source, payload: GuardAcknowledgement, engine: Database) -> GuardStatus:
    if not payload.confirmed:
        raise HTTPException(422, detail={"code": "GUARD_CONFIRMATION_REQUIRED", "message": "请先确认已人工排查风险"})
    with Session(engine) as session, session.begin():
        guard = lock_control_guards(session).get(provider)
        if guard is None:
            raise HTTPException(503, detail={"code": "GUARD_UNAVAILABLE", "message": "未初始化该来源的安全闸"})
        if active_task(session) is not None:
            raise HTTPException(409, detail={"code": "TASK_SLOT_OCCUPIED", "message": "请等待当前任务结束后再解除安全闸"})
        observed = payload.blocked_at
        if observed.tzinfo is not None:
            observed = observed.astimezone(UTC).replace(tzinfo=None)
        if guard.blocked_at != observed:
            raise HTTPException(409, detail={"code": "GUARD_CHANGED", "message": "安全闸状态已变化，请刷新并重新核对"})
        if guard.blocked_at is not None and guard.acknowledged_at is None:
            guard.acknowledged_at = datetime.now(UTC).replace(tzinfo=None)
        return guard_status(provider, guard)
