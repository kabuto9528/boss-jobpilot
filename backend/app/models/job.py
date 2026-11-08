from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, desc, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "identity_key", name="uq_jobs_source_identity"),
        Index("ix_jobs_source_priority_score_id", "source", "priority", desc("score"), desc("id")),
        Index("ix_jobs_source_recommended_score", "source", "recommended", desc("score"), desc("id")),
        Index("ix_jobs_type", "job_type"),
        CheckConstraint("source IN ('fixture', 'boss')", name="ck_jobs_source"),
        CheckConstraint("jd_state IN ('complete', 'partial', 'missing', 'unavailable')", name="ck_jobs_jd_state"),
        CheckConstraint("availability IN ('active', 'inactive', 'unknown')", name="ck_jobs_availability"),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_jobs_score"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"},
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16, collation="utf8mb4_0900_bin"), nullable=False)
    source_job_id: Mapped[str | None] = mapped_column(String(255, collation="utf8mb4_0900_bin"), nullable=True)
    identity_key: Mapped[str] = mapped_column(String(255, collation="utf8mb4_0900_bin"), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    salary_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    experience_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    jd_text: Mapped[str | None] = mapped_column(mysql.LONGTEXT, nullable=True)
    jd_state: Mapped[str] = mapped_column(mysql.VARCHAR(24, charset="ascii", collation="ascii_bin"), nullable=False, default="missing", server_default="missing")
    availability: Mapped[str] = mapped_column(mysql.VARCHAR(24, charset="ascii", collation="ascii_bin"), nullable=False, default="unknown", server_default="unknown")
    job_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    priority: Mapped[int | None] = mapped_column(mysql.SMALLINT(unsigned=True), nullable=True)
    score: Mapped[Decimal | None] = mapped_column(mysql.DECIMAL(5, 2), nullable=True)
    recommended: Mapped[bool] = mapped_column(mysql.BOOLEAN, nullable=False, default=False, server_default="0")
    score_reasons: Mapped[list | dict | None] = mapped_column(mysql.JSON, nullable=True)
    scoring_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_task_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True), ForeignKey("tasks.id", name="fk_jobs_last_task", ondelete="SET NULL"), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)"))
    last_seen_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)"))
