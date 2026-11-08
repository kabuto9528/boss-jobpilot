from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError

from backend.app.config import load_database_settings
from backend.app.db import create_database_engine
from backend.app.main import create_app
from backend.app.models.application import Application
from backend.app.models.job import Job
from backend.app.models.task import Task
from scripts.seed_demo import JOBS, seed_jobs


@pytest.fixture(scope="module")
def mysql_jobs_app():
    settings = load_database_settings(testing=True)
    assert settings.database == "boss_jobs_test"
    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            existing = set(
                connection.execute(
                    text("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()")
                ).scalars()
            )
        required = {"jobs", "applications", "tasks", "automation_guard"}
        missing = required - existing
        if missing:
            pytest.fail(
                "Apply backend/migrations/001_initial.sql to boss_jobs_test with a database administrator first; "
                f"missing tables: {', '.join(sorted(missing))}"
            )
        seed_jobs(engine)
        with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
            yield client, engine
    finally:
        engine.dispose()


def test_seed_reimport_does_not_grow_and_stays_fixture_only(mysql_jobs_app):
    _, engine = mysql_jobs_app
    keys = [job["identity_key"] for job in JOBS]
    with engine.connect() as connection:
        before = connection.execute(
            select(Job.id).where(Job.source == "fixture", Job.identity_key.in_(keys))
        ).scalars().all()
        before = len(before)
    assert before == len(JOBS)

    assert seed_jobs(engine) == len(JOBS)

    with engine.connect() as connection:
        after = connection.execute(
            select(Job.id).where(Job.source == "fixture", Job.identity_key.in_(keys))
        ).scalars().all()
        after = len(after)
        wrong_source = connection.execute(
            select(Job.id).where(Job.identity_key.in_(keys), Job.source != "fixture")
        ).scalars().all()
        wrong_source = len(wrong_source)
    assert after == before == len(JOBS)
    assert wrong_source == 0


def test_schema_has_table_separation_constraints_and_guard_rows(mysql_jobs_app):
    _, engine = mysql_jobs_app
    with engine.connect() as connection:
        unique_constraints = set(
            connection.execute(
                text(
                    "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND CONSTRAINT_TYPE = 'UNIQUE'"
                )
            ).scalars()
        )
        foreign_keys = set(
            connection.execute(
                text(
                    "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND CONSTRAINT_TYPE = 'FOREIGN KEY'"
                )
            ).scalars()
        )
        generated = set(
            connection.execute(
                text(
                    "SELECT CONCAT(TABLE_NAME, '.', COLUMN_NAME) FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND EXTRA LIKE '%GENERATED%'"
                )
            ).scalars()
        )
        guard_scopes = set(connection.execute(text("SELECT scope FROM automation_guard")).scalars())

    assert {
        "uq_tasks_request_key",
        "uq_tasks_active_slot",
        "uq_jobs_source_identity",
        "uq_applications_one_blocking_per_job",
    } <= unique_constraints
    assert {
        "fk_jobs_last_task",
        "fk_applications_job",
        "fk_applications_task",
        "fk_automation_guard_task",
    } <= foreign_keys
    assert {"tasks.active_slot", "applications.blocking_job_id"} <= generated
    assert guard_scopes == {"fixture", "boss"}


def test_generated_slots_and_foreign_keys_enforce_write_constraints(mysql_jobs_app):
    _, engine = mysql_jobs_app
    token = uuid4().hex
    request_key = f"stage4-{token}"
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            task_id = connection.execute(
                insert(Task).values(
                    request_key=request_key,
                    request_hash="a" * 64,
                    mode="review",
                    provider="fixture",
                    status="running",
                    params_json={"test_case": token},
                )
            ).inserted_primary_key[0]

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    insert(Task).values(
                        request_key=f"stage4-{uuid4().hex}",
                        request_hash="b" * 64,
                        mode="review",
                        provider="fixture",
                        status="queued",
                        params_json={"test_case": token},
                    )
                )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    insert(Task).values(
                        request_key=request_key,
                        request_hash="c" * 64,
                        mode="review",
                        provider="fixture",
                        status="failed",
                        params_json={"test_case": token},
                    )
                )

            job_id = connection.execute(
                select(Job.id).where(Job.identity_key == "fixture:ops-intern-01")
            ).scalar_one()
            connection.execute(
                insert(Application).values(job_id=job_id, task_id=task_id, origin="fixture", status="pending")
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    insert(Application).values(job_id=job_id, task_id=task_id, origin="fixture", status="uncertain")
                )

            # Failed attempts are historical rows and do not occupy the generated blocking slot.
            connection.execute(
                insert(Application).values(job_id=job_id, task_id=task_id, origin="fixture", status="failed")
            )
            connection.execute(
                insert(Application).values(job_id=job_id, task_id=task_id, origin="fixture", status="failed")
            )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    insert(Application).values(
                        job_id=18446744073709551615,
                        task_id=task_id,
                        origin="fixture",
                        status="pending",
                    )
                )
        finally:
            transaction.rollback()


def test_unicode_fixture_round_trips_without_loss(mysql_jobs_app):
    client, _ = mysql_jobs_app
    listing = client.get("/api/jobs", params={"source": "fixture", "q": "平台运维"})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    job_id = listing.json()["items"][0]["id"]

    detail = client.get(f"/api/jobs/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["company"] == "青云科技 🚀"
    assert "星际探索 ✨" in detail.json()["jd_text"]
    assert Decimal(str(detail.json()["score"])) == Decimal("88.00")


def test_jobs_filters_and_source_scope(mysql_jobs_app):
    client, _ = mysql_jobs_app
    response = client.get(
        "/api/jobs",
        params={"source": "fixture", "q": "实习生", "job_type": "实习", "recommended": "true", "min_score": 85},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["title"] for item in body["items"]} == {"平台运维实习生", "数据平台实习生"}
    assert all(item["source"] == "fixture" and item["recommended"] for item in body["items"])

    other_source = client.get("/api/jobs", params={"source": "boss"})
    assert other_source.status_code == 200
    assert other_source.json()["total"] == 0


def test_stable_order_and_pagination_have_no_gaps_or_duplicates(mysql_jobs_app):
    client, _ = mysql_jobs_app
    params = {"source": "fixture", "page_size": 2}
    first = client.get("/api/jobs", params={**params, "page": 1}).json()
    second = client.get("/api/jobs", params={**params, "page": 2}).json()
    third = client.get("/api/jobs", params={**params, "page": 3}).json()
    again = client.get("/api/jobs", params={"source": "fixture", "page_size": 100}).json()

    page_ids = [item["id"] for page in (first, second, third) for item in page["items"]]
    ordered_ids = [item["id"] for item in again["items"]]
    assert first["total"] == second["total"] == third["total"] == len(JOBS)
    assert len(page_ids) == len(set(page_ids)) == len(JOBS)
    assert page_ids == ordered_ids
    assert page_ids == [item["id"] for item in client.get("/api/jobs", params={"source": "fixture"}).json()["items"]]

    records = again["items"]
    sort_keys = [
        (
            item["priority"] if item["priority"] is not None else 65536,
            item["score"] is None,
            -(float(item["score"]) if item["score"] is not None else 0),
            -item["id"],
        )
        for item in records
    ]
    assert sort_keys == sorted(sort_keys)


def test_missing_job_returns_404_and_query_bounds_are_validated(mysql_jobs_app):
    client, _ = mysql_jobs_app
    missing = client.get("/api/jobs/9223372036854775000")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "JOB_NOT_FOUND"

    assert client.get("/api/jobs", params={"page": 0}).status_code == 422
    assert client.get("/api/jobs", params={"page_size": 101}).status_code == 422
    assert client.get("/api/jobs", params={"source": "unknown"}).status_code == 422
