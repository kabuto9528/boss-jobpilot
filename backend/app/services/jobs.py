from sqlalchemy import func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..models.job import Job
from ..schemas.jobs import JobDetail, JobListItem, JobListResponse


def _filters(*, source: str | None, q: str | None, job_type: str | None, recommended: bool | None, min_score: float | None):
    clauses = []
    if source is not None:
        clauses.append(Job.source == source)
    if q:
        # Treat SQL LIKE metacharacters as ordinary user search text.
        query = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{query}%"
        clauses.append(
            or_(
                Job.title.ilike(pattern, escape="\\"),
                Job.company.ilike(pattern, escape="\\"),
                Job.city.ilike(pattern, escape="\\"),
            )
        )
    if job_type is not None:
        clauses.append(Job.job_type == job_type)
    if recommended is not None:
        clauses.append(Job.recommended.is_(recommended))
    if min_score is not None:
        clauses.append(Job.score >= min_score)
    return clauses


def list_jobs(
    engine: Engine,
    *,
    page: int,
    page_size: int,
    source: str | None = None,
    q: str | None = None,
    job_type: str | None = None,
    recommended: bool | None = None,
    min_score: float | None = None,
) -> JobListResponse:
    clauses = _filters(source=source, q=q, job_type=job_type, recommended=recommended, min_score=min_score)
    with Session(engine) as session:
        total = session.scalar(select(func.count()).select_from(Job).where(*clauses))
        jobs = session.scalars(
            select(Job)
            .where(*clauses)
            .order_by(
                Job.priority.asc(),
                Job.score.is_(None).asc(),
                Job.score.desc(),
                Job.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    return JobListResponse(
        items=[JobListItem.model_validate(job) for job in jobs],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_job(engine: Engine, job_id: int) -> JobDetail | None:
    with Session(engine) as session:
        job = session.scalar(select(Job).where(Job.id == job_id))
    return JobDetail.model_validate(job) if job is not None else None
