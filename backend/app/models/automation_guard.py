from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AutomationGuard(Base):
    __tablename__ = "automation_guard"
    __table_args__ = (
        Index("ix_automation_guard_task_id", "task_id"),
        CheckConstraint("scope IN ('fixture', 'boss')", name="ck_automation_guard_scope"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"},
    )

    scope: Mapped[str] = mapped_column(String(16, collation="utf8mb4_0900_bin"), primary_key=True)
    blocked_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(mysql.VARCHAR(64, charset="ascii", collation="ascii_bin"), nullable=True)
    task_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True), ForeignKey("tasks.id", name="fk_automation_guard_task", ondelete="SET NULL"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
