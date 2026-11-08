from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JobListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_job_id: str | None
    identity_key: str
    source_url: str | None
    title: str
    company: str
    city: str | None
    salary_text: str | None
    experience_text: str | None
    jd_state: str
    availability: str
    job_type: str | None
    priority: int | None
    score: Decimal | None
    recommended: bool
    score_reasons: list[Any] | dict[str, Any] | None
    scoring_version: str | None
    last_task_id: int | None
    first_seen_at: datetime
    last_seen_at: datetime


class JobDetail(JobListItem):
    jd_text: str | None


class JobListResponse(BaseModel):
    items: list[JobListItem]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
