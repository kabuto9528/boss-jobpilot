from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.engine import Engine

from ..schemas.applications import ApplicationCreate, ApplicationItem, ApplicationList, ApplicationResolve, ApplicationStatus
from ..services.applications import ApplicationError, create_pending, list_applications, resolve_application
from ..services.management import Source
from .management_access import database_engine, require_local_control


router = APIRouter(prefix="/api/applications", tags=["applications"])
Database = Annotated[Engine, Depends(database_engine)]


@router.get("", response_model=ApplicationList)
def read_applications(
    engine: Database,
    source: Source = "fixture",
    status: ApplicationStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ApplicationList:
    return list_applications(engine, source, status, page, page_size)


@router.post("", response_model=ApplicationItem, status_code=201, dependencies=[Depends(require_local_control)])
def add_pending(payload: ApplicationCreate, engine: Database) -> ApplicationItem:
    try:
        return create_pending(engine, payload.job_id)
    except ApplicationError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": str(exc)}) from None


@router.post("/{application_id}/resolve", response_model=ApplicationItem, dependencies=[Depends(require_local_control)])
def resolve(
    application_id: Annotated[int, Path(gt=0)], payload: ApplicationResolve, engine: Database,
) -> ApplicationItem:
    try:
        return resolve_application(engine, application_id, payload.status, payload.evidence_summary)
    except ApplicationError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": str(exc)}) from None
