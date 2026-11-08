-- Initial schema for boss_jobs and boss_jobs_test.
-- Apply as a database administrator after confirming the selected database.

CREATE TABLE IF NOT EXISTS tasks (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    request_key VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    request_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    mode VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    provider VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    dry_run BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'queued',
    phase VARCHAR(64) NULL,
    params_json JSON NOT NULL,
    rule_snapshot JSON NULL,
    progress_json JSON NULL,
    stop_reason VARCHAR(128) NULL,
    error_code VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    active_slot TINYINT GENERATED ALWAYS AS (
        CASE WHEN status IN ('queued', 'running', 'stop_requested') THEN 1 ELSE NULL END
    ) STORED,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    started_at DATETIME(6) NULL,
    finished_at DATETIME(6) NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_tasks_request_key (request_key),
    UNIQUE KEY uq_tasks_active_slot (active_slot),
    KEY ix_tasks_status_created_at (status, created_at),
    CONSTRAINT ck_tasks_mode CHECK (mode IN ('review', 'auto')),
    CONSTRAINT ck_tasks_provider CHECK (provider IN ('fixture', 'boss')),
    CONSTRAINT ck_tasks_status CHECK (status IN ('queued', 'running', 'stop_requested', 'succeeded', 'failed', 'stopped', 'interrupted'))
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS jobs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    source VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    source_job_id VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NULL,
    identity_key VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    source_url VARCHAR(2048) NULL,
    title VARCHAR(255) NOT NULL,
    company VARCHAR(255) NOT NULL,
    city VARCHAR(128) NULL,
    salary_text VARCHAR(255) NULL,
    experience_text VARCHAR(255) NULL,
    jd_text LONGTEXT NULL,
    jd_state VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'missing',
    availability VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'unknown',
    job_type VARCHAR(64) NULL,
    priority SMALLINT UNSIGNED NULL,
    score DECIMAL(5, 2) NULL,
    recommended BOOLEAN NOT NULL DEFAULT FALSE,
    score_reasons JSON NULL,
    scoring_version VARCHAR(64) NULL,
    last_task_id BIGINT UNSIGNED NULL,
    first_seen_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    last_seen_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_jobs_source_identity (source, identity_key),
    KEY ix_jobs_source_priority_score_id (source, priority, score DESC, id DESC),
    KEY ix_jobs_source_recommended_score (source, recommended, score DESC, id DESC),
    KEY ix_jobs_type (job_type),
    CONSTRAINT fk_jobs_last_task FOREIGN KEY (last_task_id) REFERENCES tasks (id) ON DELETE SET NULL,
    CONSTRAINT ck_jobs_source CHECK (source IN ('fixture', 'boss')),
    CONSTRAINT ck_jobs_jd_state CHECK (jd_state IN ('complete', 'partial', 'missing', 'unavailable')),
    CONSTRAINT ck_jobs_availability CHECK (availability IN ('active', 'inactive', 'unknown')),
    CONSTRAINT ck_jobs_score CHECK (score IS NULL OR (score >= 0 AND score <= 100))
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS applications (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    job_id BIGINT UNSIGNED NOT NULL,
    task_id BIGINT UNSIGNED NULL,
    origin VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    status VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    started_at DATETIME(6) NULL,
    resolved_at DATETIME(6) NULL,
    result_code VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    evidence_summary TEXT NULL,
    blocking_job_id BIGINT UNSIGNED GENERATED ALWAYS AS (
        CASE WHEN status IN ('pending', 'sending', 'uncertain', 'succeeded') THEN job_id ELSE NULL END
    ) STORED,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_applications_one_blocking_per_job (blocking_job_id),
    KEY ix_applications_job_id_id (job_id, id),
    KEY ix_applications_status_updated_at (status, updated_at),
    CONSTRAINT fk_applications_job FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE RESTRICT,
    CONSTRAINT fk_applications_task FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE SET NULL,
    CONSTRAINT ck_applications_origin CHECK (origin IN ('manual', 'auto', 'fixture')),
    CONSTRAINT ck_applications_status CHECK (status IN ('pending', 'sending', 'uncertain', 'succeeded', 'failed'))
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS automation_guard (
    scope VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    blocked_at DATETIME(6) NULL,
    reason_code VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    task_id BIGINT UNSIGNED NULL,
    acknowledged_at DATETIME(6) NULL,
    PRIMARY KEY (scope),
    KEY ix_automation_guard_task_id (task_id),
    CONSTRAINT fk_automation_guard_task FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE SET NULL,
    CONSTRAINT ck_automation_guard_scope CHECK (scope IN ('fixture', 'boss'))
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

INSERT INTO automation_guard (scope)
VALUES ('fixture'), ('boss')
ON DUPLICATE KEY UPDATE scope = VALUES(scope);
