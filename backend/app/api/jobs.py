from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from ..schemas.jobs import JobDetail, JobListResponse
from ..services.jobs import get_job, list_jobs


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=JobListResponse)
def read_jobs(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    source: Literal["fixture", "boss"] | None = None,
    q: Annotated[str | None, Query(max_length=128)] = None,
    job_type: Annotated[str | None, Query(max_length=64)] = None,
    recommended: bool | None = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
) -> JobListResponse:
    engine = request.app.state.database_engine
    if engine is None:
        raise HTTPException(status_code=503, detail={"code": "DATABASE_UNAVAILABLE", "message": "数据库不可用"})
    return list_jobs(
        engine,
        page=page,
        page_size=page_size,
        source=source,
        q=q.strip() if q and q.strip() else None,
        job_type=job_type,
        recommended=recommended,
        min_score=min_score,
    )


@router.get("/{job_id}", response_model=JobDetail)
def read_job(job_id: int, request: Request) -> JobDetail:
    engine = request.app.state.database_engine
    if engine is None:
        raise HTTPException(status_code=503, detail={"code": "DATABASE_UNAVAILABLE", "message": "数据库不可用"})
    job = get_job(engine, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "职位不存在"})
    return job
