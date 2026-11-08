from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.automation_guard import AutomationGuard
from ..models.task import Task


Source = Literal["fixture", "boss"]
SOURCES = ("fixture", "boss")


def lock_control_guards(session: Session) -> dict[str, AutomationGuard]:
    # Share a lock order across admission and acknowledgement, including across sources.
    rows = session.scalars(select(AutomationGuard).order_by(AutomationGuard.scope).with_for_update())
    return {row.scope: row for row in rows}


def latch_guard(guard: AutomationGuard | None, reason: str, task_id: int | None, now: datetime) -> None:
    if guard is None:
        return
    if guard.blocked_at is not None and guard.acknowledged_at is None and guard.task_id == task_id and guard.reason_code == reason:
        return
    guard.blocked_at = now
    guard.reason_code = reason
    guard.task_id = task_id
    guard.acknowledged_at = None


def active_task(session: Session) -> Task | None:
    return session.scalar(select(Task).where(Task.active_slot == 1))


def database_timestamp(epoch: Decimal) -> datetime:
    # CURRENT_TIMESTAMP DATETIME uses the MySQL session timezone; UNIX_TIMESTAMP
    # interprets it in that same timezone. Worker-written times already use UTC.
    return datetime.fromtimestamp(float(epoch), UTC)


def utc_timestamp(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None else None
