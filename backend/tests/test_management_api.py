from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.api import settings as settings_api
from backend.app.config import load_database_settings, load_scoring_settings
from backend.app.db import create_database_engine
from backend.app.main import create_app
from backend.app.models.application import Application
from backend.app.models.automation_guard import AutomationGuard
from backend.app.models.job import Job
from backend.app.models.task import Task


@pytest.fixture
def management():
    settings = load_database_settings(testing=True)
    assert settings.database == "boss_jobs_test"
    engine = create_database_engine(settings)
    prefix = f"stage11-test-{uuid4().hex}"
    job_ids, task_ids = [], []
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        def job(source="fixture", recommended=False):
            with Session(engine) as session, session.begin():
                row = Job(source=source, identity_key=f"{prefix}-{len(job_ids)}", title=prefix, company="合成公司", recommended=recommended)
                session.add(row)
                session.flush()
                job_ids.append(row.id)
                return row.id

        def task(status, provider="fixture"):
            with Session(engine) as session, session.begin():
                row = Task(request_key=f"{prefix}-{len(task_ids)}", request_hash="a" * 64,
                           mode="review", provider=provider, status=status, params_json={})
                session.add(row)
                session.flush()
                task_ids.append(row.id)
                return row.id

        try:
            yield client, engine, job, task
        finally:
            with Session(engine) as session, session.begin():
                if job_ids:
                    session.execute(delete(Application).where(Application.job_id.in_(job_ids)))
                    session.execute(delete(Job).where(Job.id.in_(job_ids)))
                if task_ids:
                    session.execute(delete(Task).where(Task.id.in_(task_ids)))
            engine.dispose()


def test_dashboard_matches_source_filtered_lists_and_counts_attempts(management):
    client, engine, job, task = management
    baseline = {source: client.get(f"/api/dashboard?source={source}").json() for source in ("fixture", "boss")}
    fixture_job = job(recommended=True)
    boss_job = job(source="boss")
    fixture_task = task("succeeded")
    boss_task = task("running", provider="boss")
    with Session(engine) as session, session.begin():
        session.add_all([
            Application(job_id=fixture_job, status="failed", origin="fixture", task_id=fixture_task),
            Application(job_id=fixture_job, status="uncertain", origin="fixture", task_id=fixture_task),
            Application(job_id=boss_job, status="pending", origin="manual"),
        ])
    for source in ("fixture", "boss"):
        current = client.get(f"/api/dashboard?source={source}").json()
        assert current["jobs_total"] == baseline[source]["jobs_total"] + 1
        assert current["jobs_total"] == client.get(f"/api/jobs?source={source}").json()["total"]
        assert current["jobs_recommended"] == baseline[source]["jobs_recommended"] + (source == "fixture")
        assert current["jobs_recommended"] == client.get(f"/api/jobs?source={source}&recommended=true").json()["total"]
        for status, count in current["applications"].items():
            expected_delta = int(status in ("failed", "uncertain")) if source == "fixture" else int(status == "pending")
            assert count == baseline[source]["applications"][status] + expected_delta
            assert count == client.get(f"/api/applications?source={source}&status={status}").json()["total"]
        page = client.get(f"/api/applications?source={source}&page=1&page_size=1").json()
        assert len(page["items"]) == 1
        assert page["items"][0]["job"]["source"] == source
        assert all(row["provider"] == source for row in current["recent_tasks"])
        assert current["recent_tasks"][0]["task_id"] == (fixture_task if source == "fixture" else boss_task)
        if source == "fixture":
            assert current["active_task"] is None
        else:
            assert current["active_task"]["task_id"] == boss_task
    assert client.get("/api/tasks?limit=1").json()["active_task"]["task_id"] == boss_task


def test_pending_admission_and_resolution_preserve_history_and_reject_duplicates(management):
    client, engine, job, _ = management
    job_id = job()
    assert client.post("/api/applications", json={"job_id": 0}).status_code == 422
    assert client.post("/api/applications", json={"job_id": 2**53 - 1}).status_code == 404
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post("/api/applications", json={"job_id": job_id}), range(2)))
    assert sorted(r.status_code for r in responses) == [201, 409]
    row = next(r.json() for r in responses if r.status_code == 201)
    assert (row["job"]["id"], row["origin"], row["status"], row["task_id"]) == (job_id, "manual", "pending", None)
    resolve_url = f"/api/applications/{row['id']}/resolve"
    assert client.post(resolve_url, json={"status": "failed", "evidence_summary": "  "}).status_code == 422
    assert client.post(resolve_url, json={"status": "sending", "evidence_summary": "x"}).status_code == 422
    failed = client.post(resolve_url, json={"status": "failed", "evidence_summary": " 核对后确认未完成 "})
    assert failed.status_code == 200
    assert failed.json()["evidence_summary"] == "核对后确认未完成"
    created, resolved, updated = (datetime.fromisoformat(failed.json()[key]) for key in ("created_at", "resolved_at", "updated_at"))
    assert created.utcoffset() == resolved.utcoffset() == updated.utcoffset() == timedelta(0)
    assert created <= resolved <= updated + timedelta(seconds=1)
    assert client.post(resolve_url, json={"status": "succeeded", "evidence_summary": "重复修改"}).status_code == 409
    retry = client.post("/api/applications", json={"job_id": job_id})
    assert retry.status_code == 201
    assert retry.json()["id"] != row["id"]
    with Session(engine) as session:
        assert session.get(Application, row["id"]).status == "failed"


def test_uncertain_can_be_confirmed_once_but_cannot_be_requeued(management):
    client, engine, job, _ = management
    job_id, sending_job_id = job(), job()
    with Session(engine) as session, session.begin():
        uncertain = Application(job_id=job_id, status="uncertain", origin="fixture")
        sending = Application(job_id=sending_job_id, status="sending", origin="fixture")
        session.add_all([uncertain, sending])
        session.flush()
        uncertain_id, sending_id = uncertain.id, sending.id
    evidence = {"status": "succeeded", "evidence_summary": "核对到该职位已投递"}
    assert client.post(f"/api/applications/{sending_id}/resolve", json=evidence).status_code == 409
    assert client.post("/api/applications", json={"job_id": job_id}).status_code == 409
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(f"/api/applications/{uncertain_id}/resolve", json=evidence), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert client.post("/api/applications", json={"job_id": job_id}).status_code == 409


def test_settings_allowlist_and_http_control_boundaries(management, monkeypatch):
    client, engine, job, _ = management
    original = settings_api.load_app_document
    rule = load_scoring_settings()
    rule.document["scoring"]["secret"] = "stage11-test-cookie-sentinel"
    rule.document["skills"]["rules"][0]["private"] = "stage11-test-cookie-sentinel"
    monkeypatch.setattr(settings_api, "load_scoring_settings", lambda: rule)
    monkeypatch.setattr(settings_api, "load_app_document", lambda: {**original(), "password": "stage11-test-cookie-sentinel"})
    response = client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"search", "review_limits", "poll_interval_ms", "browser_timeout_ms", "scoring", "capabilities", "guards", "task_busy"}
    assert data["scoring"]["version"] == rule.version
    assert data["scoring"]["recommendation_threshold"] == rule.document["scoring"]["recommendation_threshold"]
    assert not data["capabilities"]["boss"]["review_enabled"]
    assert all(not capability["auto_enabled"] for capability in data["capabilities"].values())
    assert all(word not in response.text.lower() for word in ("sentinel", "password", "profile", "cookie", "database", "patterns"))
    assert {row["provider"] for row in data["guards"]} == {"fixture", "boss"}
    job_id = job()
    assert client.post("/api/applications", json={"job_id": job_id}, headers={"Origin": "https://example.invalid"}).status_code == 403
    assert client.post("/api/applications", content='{}', headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.post("/api/applications", json={"job_id": job_id}, headers={"Origin": "http://127.0.0.1:5173"}).status_code == 201
    with Session(engine) as session:
        before = session.scalar(select(func.count()).select_from(Task))
    for provider in ("fixture", "boss"):
        response = client.post("/api/tasks", json={
            "mode": "auto", "provider": provider, "request_key": uuid4().hex, "params": {"keywords": ["样例"]},
        })
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "AUTO_NOT_AVAILABLE"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Task)) == before


def test_guard_requires_current_incident_confirmation_and_idle_slot(management):
    client, engine, _, task = management
    previous_task = task("stopped")
    active = task("running", provider="boss")
    blocked_at = datetime.now(UTC).replace(tzinfo=None)
    with Session(engine) as session, session.begin():
        guard = session.get(AutomationGuard, "fixture")
        old = (guard.blocked_at, guard.reason_code, guard.task_id, guard.acknowledged_at)
        guard.blocked_at, guard.reason_code, guard.task_id, guard.acknowledged_at = blocked_at, "SECURITY_CHECK", previous_task, None
    try:
        url = "/api/automation-guard/fixture/acknowledge"
        payload = {"confirmed": True, "blocked_at": blocked_at.isoformat()}
        assert client.post(url, json={**payload, "confirmed": False}).status_code == 422
        assert client.post(url, json=payload).json()["detail"]["code"] == "TASK_SLOT_OCCUPIED"
        with Session(engine) as session, session.begin():
            session.get(Task, active).status = "stopped"
        denied = client.post("/api/tasks", json={
            "mode": "review", "provider": "fixture", "request_key": uuid4().hex, "params": {"keywords": ["样例"]},
        })
        assert denied.status_code == 423
        assert client.post(url, json={**payload, "blocked_at": "2020-01-01T00:00:00"}).json()["detail"]["code"] == "GUARD_CHANGED"
        ack = client.post(url, json=payload)
        assert ack.status_code == 200
        assert ack.json()["state"] == "clear" and ack.json()["acknowledged_at"]
        assert client.post(url, json=payload).json() == ack.json()
        assert client.get(f"/api/tasks/{previous_task}").json()["status"] == "stopped"
        assert client.get("/api/tasks").json()["active_task"] is None
    finally:
        with Session(engine) as session, session.begin():
            guard = session.get(AutomationGuard, "fixture")
            guard.blocked_at, guard.reason_code, guard.task_id, guard.acknowledged_at = old
