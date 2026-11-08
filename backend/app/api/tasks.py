from hashlib import sha256
import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import ScoringConfigError, load_scoring_settings
from ..models.automation_guard import AutomationGuard
from ..models.task import Task
from ..runner.task_runner import TERMINAL
from ..schemas.tasks import StopResult, TaskAccepted, TaskCreate, TaskList, TaskStatus


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _status(task: Task) -> TaskStatus:
    return TaskStatus(
        task_id=task.id,
        mode=task.mode,
        provider=task.provider,
        status=task.status,
        phase=task.phase,
        progress=task.progress_json or {},
        stop_reason=task.stop_reason,
        error_code=task.error_code,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )


def _key_conflict(existing: Task, request_hash: str) -> TaskAccepted:
    if existing.request_hash != request_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "REQUEST_KEY_REUSED", "message": "该 request_key 已用于不同请求"},
        )
    return TaskAccepted(task_id=existing.id, status=existing.status, status_url=f"/api/tasks/{existing.id}")


@router.post("", response_model=TaskAccepted, status_code=status.HTTP_202_ACCEPTED)
def create_task(payload: TaskCreate, request: Request, response: Response) -> TaskAccepted:
    engine = request.app.state.database_engine
    if engine is None:
        raise HTTPException(status_code=503, detail={"code": "DATABASE_UNAVAILABLE", "message": "数据库不可用"})
    if payload.mode != "review":
        raise HTTPException(status_code=409, detail={"code": "AUTO_NOT_AVAILABLE", "message": "当前阶段只允许 Review 任务"})
    if payload.provider != "fixture":
        raise HTTPException(status_code=403, detail={"code": "PROVIDER_DISABLED", "message": "真实 BOSS Review 尚未完成前置验收或许可核验"})

    params = payload.params.model_dump(mode="json")
    request_body = {"mode": payload.mode, "provider": payload.provider, "params": params}
    request_hash = sha256(
        json.dumps(request_body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    try:
        scoring = load_scoring_settings()
    except ScoringConfigError:
        raise HTTPException(status_code=503, detail={"code": "SCORING_CONFIG_INVALID", "message": "评分规则暂不可用"}) from None

    try:
        with Session(engine) as session, session.begin():
            existing = session.scalar(select(Task).where(Task.request_key == payload.request_key).with_for_update())
            if existing is not None:
                accepted = _key_conflict(existing, request_hash)
            else:
                guard = session.get(AutomationGuard, payload.provider)
                if guard is not None and guard.blocked_at is not None and guard.acknowledged_at is None:
                    raise HTTPException(
                        status_code=423,
                        detail={"code": "PROVIDER_PAUSED", "message": "该数据源因安全停止而暂停，请先人工检查并解除安全闸"},
                    )
                active = session.scalar(
                    select(Task).where(Task.status.in_(("queued", "running", "stop_requested"))).order_by(Task.id).limit(1)
                )
                if active is not None:
                    raise HTTPException(
                        status_code=409,
                        detail={"code": "TASK_SLOT_OCCUPIED", "message": "已有任务占用后台执行槽", "active_task_id": active.id},
                    )
                task = Task(
                    request_key=payload.request_key,
                    request_hash=request_hash,
                    mode=payload.mode,
                    provider=payload.provider,
                    dry_run=True,
                    status="queued",
                    phase="queued",
                    params_json=params,
                    rule_snapshot=scoring.document,
                    progress_json={
                        "keyword_count": len(params["keywords"]),
                        "keyword_index": 0,
                        "pages_attempted": 0,
                        "details_attempted": 0,
                        "jobs_found": 0,
                        "jobs_saved": 0,
                        "duplicates": 0,
                        "skipped": {},
                    },
                )
                session.add(task)
                session.flush()
                accepted = TaskAccepted(task_id=task.id, status="queued", status_url=f"/api/tasks/{task.id}")
    except IntegrityError:
        with Session(engine) as session:
            existing = session.scalar(select(Task).where(Task.request_key == payload.request_key))
            if existing is not None:
                accepted = _key_conflict(existing, request_hash)
            else:
                active = session.scalar(
                    select(Task).where(Task.status.in_(("queued", "running", "stop_requested"))).order_by(Task.id).limit(1)
                )
                raise HTTPException(
                    status_code=409,
                    detail={"code": "TASK_SLOT_OCCUPIED", "message": "已有任务占用后台执行槽", "active_task_id": active.id if active else None},
                ) from None
    response.headers["Location"] = accepted.status_url
    request.app.state.task_runner.wake()
    return accepted


@router.get("", response_model=TaskList)
def list_tasks(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> TaskList:
    engine = request.app.state.database_engine
    if engine is None:
        raise HTTPException(status_code=503, detail={"code": "DATABASE_UNAVAILABLE", "message": "数据库不可用"})
    with Session(engine) as session:
        total = session.scalar(select(func.count()).select_from(Task)) or 0
        tasks = session.scalars(select(Task).order_by(desc(Task.created_at), desc(Task.id)).limit(limit)).all()
    return TaskList(items=[_status(task) for task in tasks], total=total)


@router.get("/{task_id}", response_model=TaskStatus)
def read_task(task_id: int, request: Request) -> TaskStatus:
    engine = request.app.state.database_engine
    if engine is None:
        raise HTTPException(status_code=503, detail={"code": "DATABASE_UNAVAILABLE", "message": "数据库不可用"})
    with Session(engine) as session:
        task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND", "message": "任务不存在"})
    return _status(task)


@router.post("/{task_id}/stop", response_model=StopResult)
def stop_task(task_id: int, request: Request) -> StopResult:
    engine = request.app.state.database_engine
    if engine is None:
        raise HTTPException(status_code=503, detail={"code": "DATABASE_UNAVAILABLE", "message": "数据库不可用"})
    stopped = request.app.state.task_runner.request_stop(task_id)
    with Session(engine) as session:
        task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND", "message": "任务不存在"})
    if not stopped and task.status not in TERMINAL:
        raise HTTPException(status_code=409, detail={"code": "TASK_STOP_FAILED", "message": "任务状态已变化，请刷新后重试"})
    return StopResult(task=_status(task))
