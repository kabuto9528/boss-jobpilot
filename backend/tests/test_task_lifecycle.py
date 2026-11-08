import time
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import load_browser_settings, load_database_settings, load_scoring_settings
from backend.app.db import create_database_engine
from backend.app.main import create_app
from backend.app.models.application import Application
from backend.app.models.automation_guard import AutomationGuard
from backend.app.models.task import Task
from backend.app.runner.instance_lock import (
    TaskRunnerAlreadyActive,
    acquire_task_runner_lock,
    release_task_runner_lock,
)
from backend.app.services import review as review_service


def _key() -> str:
    return f"stage10-test-{uuid4().hex}"


def _body(*, keyword: str, request_key: str | None = None) -> dict:
    return {
        "mode": "review",
        "provider": "fixture",
        "request_key": request_key or _key(),
        "params": {"keywords": [keyword], "city": "", "max_pages": 1, "max_jobs": 5},
    }


def _wait_for_terminal(client: TestClient, task_id: int, timeout: float = 12.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        state = response.json()
        if state["status"] in {"succeeded", "failed", "stopped", "interrupted"}:
            return state
        time.sleep(0.04)
    raise AssertionError(f"task {task_id} did not finish before timeout")


@pytest.fixture
def mysql_test_database():
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
        real_guard = session.get(AutomationGuard, "boss")
        assert real_guard is not None
        real_guard.blocked_at = None
        real_guard.reason_code = None
        real_guard.task_id = None
        real_guard.acknowledged_at = None
    try:
        yield engine, settings
    finally:
        with Session(engine) as session, session.begin():
            guard = session.get(AutomationGuard, "fixture")
            if guard is not None:
                guard.blocked_at = None
                guard.reason_code = None
                guard.task_id = None
                guard.acknowledged_at = None
            real_guard = session.get(AutomationGuard, "boss")
            if real_guard is not None:
                real_guard.blocked_at = None
                real_guard.reason_code = None
                real_guard.task_id = None
                real_guard.acknowledged_at = None
        engine.dispose()


@pytest.fixture
def mysql_task_app(mysql_test_database):
    engine, settings = mysql_test_database
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        yield client, engine, settings


def test_slow_review_returns_202_fast_is_idempotent_and_occupies_one_slot(mysql_task_app):
    client, engine, _ = mysql_task_app
    with Session(engine) as session:
        applications_before = session.scalar(select(func.count()).select_from(Application))

    body = _body(keyword="慢读取")
    started = time.perf_counter()
    response = client.post("/api/tasks", json=body)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert response.status_code == 202
    assert elapsed_ms < 1200
    accepted = response.json()
    assert accepted["task_id"] > 0
    assert accepted["status_url"] == f"/api/tasks/{accepted['task_id']}"

    duplicate = client.post("/api/tasks", json=body)
    assert duplicate.status_code == 202
    assert duplicate.json()["task_id"] == accepted["task_id"]

    changed_payload = {**body, "params": {**body["params"], "keywords": ["运维实习生"]}}
    key_conflict = client.post("/api/tasks", json=changed_payload)
    assert key_conflict.status_code == 409
    assert key_conflict.json()["detail"]["code"] == "REQUEST_KEY_REUSED"

    occupied = client.post("/api/tasks", json=_body(keyword="运维实习生"))
    assert occupied.status_code == 409
    assert occupied.json()["detail"]["code"] == "TASK_SLOT_OCCUPIED"

    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/ready").json() == {"status": "ready"}
    final = _wait_for_terminal(client, accepted["task_id"])
    assert final["status"] == "succeeded"
    assert final["progress"]["jobs_saved"] == 1
    assert final["progress"]["browser_submit_calls"] == 0

    history = client.get("/api/tasks", params={"limit": 100})
    assert history.status_code == 200
    assert any(item["task_id"] == accepted["task_id"] for item in history.json()["items"])
    with Session(engine) as session:
        applications_after = session.scalar(select(func.count()).select_from(Application))
    assert applications_after == applications_before


def test_running_review_can_be_stopped_without_submission_or_application_rows(mysql_task_app):
    client, engine, settings = mysql_task_app
    with Session(engine) as session:
        applications_before = session.scalar(select(func.count()).select_from(Application))

    accepted = client.post("/api/tasks", json=_body(keyword="慢读取")).json()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        state = client.get(accepted["status_url"]).json()
        if state["status"] == "running":
            break
        time.sleep(0.02)
    assert state["status"] == "running"

    stop_response = client.post(f"/api/tasks/{accepted['task_id']}/stop")
    assert stop_response.status_code == 200
    assert stop_response.json()["task"]["status"] == "stop_requested"
    final = _wait_for_terminal(client, accepted["task_id"])
    assert final["status"] == "stopped"
    assert final["stop_reason"] == "USER_STOPPED"
    assert final["progress"]["browser_submit_calls"] == 0

    with Session(engine) as session:
        applications_after = session.scalar(select(func.count()).select_from(Application))
        stopped_task = session.get(Task, accepted["task_id"])
    assert applications_after == applications_before
    assert stopped_task is not None and stopped_task.active_slot is None
    assert not list(load_browser_settings().profile_root.glob(f"task-{accepted['task_id']}-*"))


def test_boss_review_and_auto_mode_remain_disabled(mysql_task_app):
    client, engine, _ = mysql_task_app
    with Session(engine) as session:
        tasks_before = session.scalar(select(func.count()).select_from(Task))

    boss = client.post("/api/tasks", json={**_body(keyword="运维实习生"), "provider": "boss"})
    assert boss.status_code == 403
    assert boss.json()["detail"]["code"] == "PROVIDER_DISABLED"

    auto = client.post("/api/tasks", json={**_body(keyword="运维实习生"), "mode": "auto"})
    assert auto.status_code == 409
    assert auto.json()["detail"]["code"] == "AUTO_NOT_AVAILABLE"

    with Session(engine) as session:
        tasks_after = session.scalar(select(func.count()).select_from(Task))
    assert tasks_after == tasks_before


def test_startup_marks_orphaned_real_task_interrupted_and_locks_real_guard(mysql_test_database):
    engine, settings = mysql_test_database
    scoring = load_scoring_settings()
    key = _key()
    with Session(engine) as session, session.begin():
        task = Task(
            request_key=key,
            request_hash="a" * 64,
            mode="review",
            provider="boss",
            status="running",
            phase="reading",
            params_json={"keywords": ["运维实习生"], "city": None, "max_pages": 1, "max_jobs": 5},
            rule_snapshot=scoring.document,
            progress_json={"details_attempted": 1},
        )
        session.add(task)
        session.flush()
        task_id = task.id

    with TestClient(create_app(settings), base_url="http://127.0.0.1") as restarted:
        state = restarted.get(f"/api/tasks/{task_id}").json()
        assert state["status"] == "interrupted"
        assert state["stop_reason"] == "PROCESS_RESTART"
        assert state["error_code"] == "PROCESS_RESTART"
        with Session(engine) as session:
            guard = session.get(AutomationGuard, "boss")
            assert guard is not None
            assert guard.reason_code == "PROCESS_RESTART"
            assert guard.task_id == task_id

    with Session(engine) as session:
        active = session.scalar(
            select(func.count()).select_from(Task).where(Task.status.in_(("queued", "running", "stop_requested")))
        )
    assert active == 0


def test_startup_interrupts_a_persisted_queued_review_without_replaying_it(mysql_test_database):
    engine, settings = mysql_test_database
    scoring = load_scoring_settings()
    with Session(engine) as session, session.begin():
        task = Task(
            request_key=_key(),
            request_hash="b" * 64,
            mode="review",
            provider="fixture",
            status="queued",
            phase="queued",
            params_json={"keywords": ["没有职位"], "city": None, "max_pages": 1, "max_jobs": 1},
            rule_snapshot=scoring.document,
            progress_json={"keyword_count": 1},
        )
        session.add(task)
        session.flush()
        task_id = task.id

    with TestClient(create_app(settings), base_url="http://127.0.0.1") as restarted:
        state = restarted.get(f"/api/tasks/{task_id}").json()
        assert state["status"] == "interrupted"
        assert state["stop_reason"] == "PROCESS_RESTART"
        assert state["error_code"] == "PROCESS_RESTART"
        time.sleep(0.1)
        state_after_wait = restarted.get(f"/api/tasks/{task_id}").json()
        assert state_after_wait["status"] == "interrupted"
        with Session(engine) as session:
            active = session.scalar(
                select(func.count()).select_from(Task).where(Task.status.in_(("queued", "running", "stop_requested")))
            )
        assert active == 0


def test_only_one_project_task_runner_can_hold_the_instance_lock():
    first = acquire_task_runner_lock()
    try:
        with pytest.raises(TaskRunnerAlreadyActive):
            acquire_task_runner_lock()
    finally:
        release_task_runner_lock(first)


def test_database_write_failure_stops_review_before_more_browser_reads(mysql_task_app, monkeypatch):
    client, engine, settings = mysql_task_app
    with Session(engine) as session:
        applications_before = session.scalar(select(func.count()).select_from(Application))
    requests = []
    original_context = review_service.persistent_context

    class ObservedContext:
        def __init__(self, *args, **kwargs):
            self._manager = original_context(*args, **kwargs)
            self._context = None

        def __enter__(self):
            self._context = self._manager.__enter__()
            self._context.on("request", lambda request: requests.append((request.method, request.url)))
            return self._context

        def __exit__(self, *args):
            return self._manager.__exit__(*args)

    def fail_write(*_args, **_kwargs):
        raise SQLAlchemyError("synthetic database write failure")

    monkeypatch.setattr(review_service, "persistent_context", ObservedContext)
    monkeypatch.setattr(review_service, "_persist_scored_job", fail_write)
    accepted = client.post("/api/tasks", json=_body(keyword="运维实习生"))
    assert accepted.status_code == 202
    final = _wait_for_terminal(client, accepted.json()["task_id"])
    assert final["status"] == "failed"
    assert final["error_code"] == "DATABASE_WRITE_FAILED"
    assert "synthetic" not in str(final)
    assert len(requests) == 2
    assert all(method == "GET" for method, _ in requests)
    with Session(engine) as session:
        applications_after = session.scalar(select(func.count()).select_from(Application))
        failed_task = session.get(Task, accepted.json()["task_id"])
    assert applications_after == applications_before
    assert failed_task is not None and failed_task.active_slot is None
    assert not list(load_browser_settings().profile_root.glob(f"task-{accepted.json()['task_id']}-*"))
