from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..services.management import Source


ApplicationStatus = Literal["pending", "sending", "succeeded", "failed", "uncertain"]
Resolution = Literal["succeeded", "failed"]


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: int = Field(gt=0, strict=True)


class ApplicationResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Resolution
    evidence_summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ApplicationJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: Source
    title: str
    company: str
    city: str | None


class ApplicationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job: ApplicationJob
    task_id: int | None
    status: ApplicationStatus
    origin: Literal["manual", "fixture", "auto"]
    result_code: str | None
    evidence_summary: str | None
    started_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ApplicationList(BaseModel):
    items: list[ApplicationItem]
    total: int
    page: int
    page_size: int
