from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.application import Application
from ..models.job import Job
from ..schemas.applications import ApplicationItem, ApplicationJob, ApplicationList, ApplicationStatus, Resolution
from .management import Source, database_timestamp, utc_timestamp


class ApplicationError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def _item(row: Application, job: Job) -> ApplicationItem:
    return ApplicationItem(
        id=row.id, job=ApplicationJob.model_validate(job), task_id=row.task_id, origin=row.origin,
        status=row.status, result_code=row.result_code, evidence_summary=row.evidence_summary,
        started_at=utc_timestamp(row.started_at), resolved_at=utc_timestamp(row.resolved_at),
        created_at=database_timestamp(row.created_epoch), updated_at=database_timestamp(row.updated_epoch),
    )


def list_applications(engine: Engine, source: Source, status: ApplicationStatus | None, page: int, size: int) -> ApplicationList:
    base = select(Application, Job).join(Job, Job.id == Application.job_id).where(Job.source == source)
    if status:
        base = base.where(Application.status == status)
    with Session(engine) as session:
        total = session.scalar(select(func.count()).select_from(base.with_only_columns(Application.id).subquery())) or 0
        rows = session.execute(
            base.order_by(Application.updated_at.desc(), Application.id.desc()).offset((page - 1) * size).limit(size)
        )
        return ApplicationList(items=[_item(row, job) for row, job in rows], total=total, page=page, page_size=size)


def _blocked() -> ApplicationError:
    return ApplicationError(409, "APPLICATION_EXISTS", "该职位已有待处理、待核对或已投递记录")


def create_pending(engine: Engine, job_id: int) -> ApplicationItem:
    try:
        with Session(engine) as session, session.begin():
            job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if job is None:
                raise ApplicationError(404, "JOB_NOT_FOUND", "职位不存在")
            if session.scalar(select(Application.id).where(Application.blocking_job_id == job_id)) is not None:
                raise _blocked()
            row = Application(job_id=job_id, origin="manual", status="pending")
            session.add(row)
            session.flush()
            session.refresh(row)
            return _item(row, job)
    except IntegrityError as exc:
        if exc.orig.args[0] == 1062 and "uq_applications_one_blocking_per_job" in str(exc.orig):
            raise _blocked() from None
        raise


def resolve_application(engine: Engine, application_id: int, status: Resolution, evidence: str) -> ApplicationItem:
    with Session(engine) as session, session.begin():
        row = session.scalar(select(Application).where(Application.id == application_id).with_for_update())
        if row is None:
            raise ApplicationError(404, "APPLICATION_NOT_FOUND", "投递记录不存在")
        if row.status not in ("pending", "uncertain"):
            raise ApplicationError(409, "APPLICATION_NOT_RESOLVABLE", "仅待投递或待核对的记录可以人工确认")
        job = session.get(Job, row.job_id)
        row.status = status
        row.resolved_at = datetime.now(UTC).replace(tzinfo=None)
        row.result_code = "MANUAL_CONFIRMED"
        row.evidence_summary = evidence
        session.flush()
        session.refresh(row)
        return _item(row, job)
