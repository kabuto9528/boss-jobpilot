from typing import get_args

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..models.application import Application
from ..models.job import Job
from ..models.task import Task
from ..schemas.applications import ApplicationStatus
from ..schemas.tasks import TaskStatus
from ..services.management import Source, active_task
from .applications import Database
from .tasks import task_status


router = APIRouter(tags=["dashboard"])


class Dashboard(BaseModel):
    source: Source
    jobs_total: int
    jobs_recommended: int
    applications: dict[ApplicationStatus, int]
    active_task: TaskStatus | None
    recent_tasks: list[TaskStatus]


@router.get("/api/dashboard", response_model=Dashboard)
def read_dashboard(engine: Database, source: Source = "fixture") -> Dashboard:
    with Session(engine) as session:
        total, recommended = session.execute(
            select(func.count(), func.count(case((Job.recommended.is_(True), 1)))).select_from(Job).where(Job.source == source)
        ).one()
        attempts = dict.fromkeys(get_args(ApplicationStatus), 0)
        attempts.update(session.execute(
            select(Application.status, func.count()).join(Job, Job.id == Application.job_id)
            .where(Job.source == source).group_by(Application.status)
        ).all())
        active = active_task(session)
        recent = session.scalars(
            select(Task).where(Task.provider == source).order_by(Task.created_at.desc(), Task.id.desc()).limit(5)
        )
        return Dashboard(
            source=source, jobs_total=total, jobs_recommended=recommended, applications=attempts,
            active_task=task_status(active) if active and active.provider == source else None,
            recent_tasks=[task_status(task) for task in recent],
        )
