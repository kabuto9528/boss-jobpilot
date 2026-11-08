from datetime import datetime

from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, column_property, mapped_column

from .base import Base


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("blocking_job_id", name="uq_applications_one_blocking_per_job"),
        Index("ix_applications_job_id_id", "job_id", "id"),
        Index("ix_applications_status_updated_at", "status", "updated_at"),
        CheckConstraint("origin IN ('manual', 'auto', 'fixture')", name="ck_applications_origin"),
        CheckConstraint("status IN ('pending', 'sending', 'uncertain', 'succeeded', 'failed')", name="ck_applications_status"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"},
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), ForeignKey("jobs.id", name="fk_applications_job", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True), ForeignKey("tasks.id", name="fk_applications_task", ondelete="SET NULL"), nullable=True
    )
    origin: Mapped[str] = mapped_column(mysql.VARCHAR(16, charset="ascii", collation="ascii_bin"), nullable=False)
    status: Mapped[str] = mapped_column(mysql.VARCHAR(16, charset="ascii", collation="ascii_bin"), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
    result_code: Mapped[str | None] = mapped_column(mysql.VARCHAR(64, charset="ascii", collation="ascii_bin"), nullable=True)
    evidence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocking_job_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True),
        Computed("CASE WHEN status IN ('pending', 'sending', 'uncertain', 'succeeded') THEN job_id ELSE NULL END", persisted=True),
    )
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)"))
    updated_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6), nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
    )
    created_epoch = column_property(func.unix_timestamp(created_at))
    updated_epoch = column_property(func.unix_timestamp(updated_at))
