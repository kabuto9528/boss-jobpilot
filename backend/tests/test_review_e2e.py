from decimal import Decimal
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import load_browser_settings, load_database_settings
from backend.app.db import create_database_engine
from backend.app.main import create_app
from backend.app.models.application import Application
from backend.app.models.automation_guard import AutomationGuard
from backend.app.models.job import Job
from backend.app.models.task import Task


def _body(keyword: str) -> dict:
    return {
        "mode": "review",
        "provider": "fixture",
        "request_key": f"stage10-e2e-{uuid4().hex}",
        "params": {"keywords": [keyword], "city": "", "max_pages": 2, "max_jobs": 5},
    }


def _wait(client: TestClient, url: str, timeout: float = 12.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(url)
        assert response.status_code == 200
        state = response.json()
        if state["status"] in {"succeeded", "failed", "stopped", "interrupted"}:
            return state
        time.sleep(0.04)
    raise AssertionError("Review task did not reach a terminal state")


@pytest.fixture
def mysql_review_app():
    settings = load_database_settings(testing=True)
    assert settings.database == "boss_jobs_test"
    engine = create_database_engine(settings)
    with Session(engine) as session, session.begin():
        guard = session.get(AutomationGuard, "fixture")
        assert guard is not None
        guard.blocked_at = None
        guard.reason_code = None
        guard.task_id = None
        guard.acknowledged_at = None
    try:
        with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
            yield client, engine
    finally:
        with Session(engine) as session, session.begin():
            guard = session.get(AutomationGuard, "fixture")
            if guard is not None:
                guard.blocked_at = None
                guard.reason_code = None
                guard.task_id = None
                guard.acknowledged_at = None
        engine.dispose()


def test_review_reads_scores_persists_once_and_jobs_api_exposes_results(mysql_review_app):
    client, engine = mysql_review_app
    with Session(engine) as session:
        applications_before = session.scalar(select(func.count()).select_from(Application))

    first_accepted = client.post("/api/tasks", json=_body("运维实习生"))
    assert first_accepted.status_code == 202
    first = _wait(client, first_accepted.json()["status_url"])
    assert first["status"] == "succeeded"
    assert first["progress"]["jobs_saved"] == 4
    assert first["progress"]["browser_submit_calls"] == 0

    keys = [
        "fixture:fixture-job-001",
        "fixture:fixture-job-002",
        "fixture:fixture-job-003",
        "url:a52dc5282cef0396aec50229db2186b2904e43fe335a4ce83da4cd048c97d6e5",
    ]
    with Session(engine) as session:
        first_rows = session.scalars(select(Job).where(Job.identity_key.in_(keys))).all()
        assert len(first_rows) == len(keys)
        first_ids = {row.identity_key: row.id for row in first_rows}
        first_seen = {row.identity_key: row.first_seen_at for row in first_rows}
        first_last_seen = {row.identity_key: row.last_seen_at for row in first_rows}
        assert all(row.score is not None and row.scoring_version == "stage-09.1" for row in first_rows)
        assert all(isinstance(row.score_reasons, dict) and row.score_reasons.get("evidence") for row in first_rows)

    time.sleep(0.02)
    second_accepted = client.post("/api/tasks", json=_body("运维实习生"))
    assert second_accepted.status_code == 202
    second = _wait(client, second_accepted.json()["status_url"])
    assert second["status"] == "succeeded"
    assert second["progress"]["jobs_saved"] == 4
    assert second["progress"]["browser_submit_calls"] == 0

    listing = client.get("/api/jobs", params={"source": "fixture", "page": 1, "page_size": 20})
    assert listing.status_code == 200
    by_key = {item["identity_key"]: item for item in listing.json()["items"]}
    assert set(keys) <= set(by_key)
    assert by_key[keys[0]]["score"] is not None
    assert by_key[keys[0]]["recommended"] is True
    assert by_key[keys[0]]["score_reasons"]["reasons"]
    detail = client.get(f"/api/jobs/{by_key[keys[0]]['id']}")
    assert detail.status_code == 200
    assert detail.json()["jd_text"]
    assert Decimal(str(detail.json()["score"])) >= Decimal("0")

    with Session(engine) as session:
        rows_after_repeat = session.scalars(select(Job).where(Job.identity_key.in_(keys))).all()
        applications_after_repeat = session.scalar(select(func.count()).select_from(Application))
        assert len(rows_after_repeat) == 4
        assert {row.identity_key: row.id for row in rows_after_repeat} == first_ids
        assert all(row.first_seen_at == first_seen[row.identity_key] for row in rows_after_repeat)
        assert all(row.last_seen_at > first_last_seen[row.identity_key] for row in rows_after_repeat)
        assert all(row.last_task_id == second["task_id"] for row in rows_after_repeat)
        assert applications_after_repeat == applications_before

    risk_accepted = client.post("/api/tasks", json=_body("风险详情"))
    assert risk_accepted.status_code == 202
    risk = _wait(client, risk_accepted.json()["status_url"])
    assert risk["status"] == "stopped"
    assert risk["stop_reason"] == "SECURITY_CHECK"
    assert risk["progress"]["jobs_saved"] == 1
    assert risk["progress"]["browser_submit_calls"] == 0

    with Session(engine) as session:
        applications_after_risk = session.scalar(select(func.count()).select_from(Application))
        job_count_after_risk = session.scalar(select(func.count()).select_from(Job).where(Job.identity_key.in_(keys)))
        guard = session.get(AutomationGuard, "fixture")
        risk_task = session.get(Task, risk["task_id"])
        assert guard is not None and guard.reason_code == "SECURITY_CHECK"
        assert applications_after_risk == applications_before
        assert job_count_after_risk == 4
        assert risk_task is not None and risk_task.active_slot is None
    assert not list(load_browser_settings().profile_root.glob(f"task-{risk['task_id']}-*"))

    paused = client.post("/api/tasks", json=_body("运维实习生"))
    assert paused.status_code == 423
