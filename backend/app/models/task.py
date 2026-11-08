from datetime import datetime

from sqlalchemy import CheckConstraint, Computed, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, column_property, mapped_column

from .base import Base


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("request_key", name="uq_tasks_request_key"),
        UniqueConstraint("active_slot", name="uq_tasks_active_slot"),
        Index("ix_tasks_status_created_at", "status", "created_at"),
        CheckConstraint("mode IN ('review', 'auto')", name="ck_tasks_mode"),
        CheckConstraint("provider IN ('fixture', 'boss')", name="ck_tasks_provider"),
        CheckConstraint(
            "status IN ('queued', 'running', 'stop_requested', 'succeeded', 'failed', 'stopped', 'interrupted')",
            name="ck_tasks_status",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"},
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    request_key: Mapped[str] = mapped_column(String(128, collation="utf8mb4_0900_bin"), nullable=False)
    request_hash: Mapped[str] = mapped_column(mysql.CHAR(64, charset="ascii", collation="ascii_bin"), nullable=False)
    mode: Mapped[str] = mapped_column(mysql.VARCHAR(16, charset="ascii", collation="ascii_bin"), nullable=False)
    provider: Mapped[str] = mapped_column(mysql.VARCHAR(16, charset="ascii", collation="ascii_bin"), nullable=False)
    dry_run: Mapped[bool] = mapped_column(mysql.BOOLEAN, nullable=False, default=True, server_default="1")
    status: Mapped[str] = mapped_column(mysql.VARCHAR(24, charset="ascii", collation="ascii_bin"), nullable=False, default="queued", server_default="queued")
    phase: Mapped[str | None] = mapped_column(String(64), nullable=True)
    params_json: Mapped[dict] = mapped_column(mysql.JSON, nullable=False)
    rule_snapshot: Mapped[dict | None] = mapped_column(mysql.JSON, nullable=True)
    progress_json: Mapped[dict | None] = mapped_column(mysql.JSON, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(mysql.VARCHAR(64, charset="ascii", collation="ascii_bin"), nullable=True)
    active_slot: Mapped[int | None] = mapped_column(
        mysql.TINYINT(unsigned=True),
        Computed("CASE WHEN status IN ('queued', 'running', 'stop_requested') THEN 1 ELSE NULL END", persisted=True),
    )
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)"))
    started_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6), nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
    )
    created_epoch = column_property(func.unix_timestamp(created_at))
    updated_epoch = column_property(func.unix_timestamp(updated_at))
