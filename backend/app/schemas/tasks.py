from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MAX_KEYWORDS = 5
MAX_PAGES = 5
MAX_JOBS = 20


class ReviewTaskParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords: list[str] = Field(min_length=1, max_length=MAX_KEYWORDS)
    city: str | None = Field(default=None, max_length=64)
    max_pages: int = Field(default=2, ge=1, le=MAX_PAGES)
    max_jobs: int = Field(default=5, ge=1, le=MAX_JOBS)

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, values: list[str]) -> list[str]:
        cleaned = [" ".join(value.split()) for value in values if isinstance(value, str)]
        if len(cleaned) != len(values) or any(not value for value in cleaned):
            raise ValueError("keywords must contain nonempty strings")
        if len({value.casefold() for value in cleaned}) != len(cleaned):
            raise ValueError("keywords must be unique")
        return cleaned

    @field_validator("city")
    @classmethod
    def clean_city(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value and value.strip() else None


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["review", "auto"] = "review"
    provider: Literal["fixture", "boss"] = "fixture"
    request_key: str = Field(min_length=1, max_length=128)
    params: ReviewTaskParams

    @field_validator("request_key")
    @classmethod
    def clean_request_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("request_key cannot be empty")
        return value


class TaskAccepted(BaseModel):
    task_id: int
    status: str
    status_url: str


class TaskStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: int
    mode: str
    provider: str
    status: str
    phase: str | None
    progress: dict = Field(default_factory=dict)
    stop_reason: str | None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class TaskList(BaseModel):
    items: list[TaskStatus]
    total: int = Field(ge=0)
    active_task: TaskStatus | None


class StopResult(BaseModel):
    task: TaskStatus
