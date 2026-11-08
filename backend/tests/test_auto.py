from concurrent.futures import ThreadPoolExecutor
from subprocess import CREATE_NO_WINDOW, run
import sys
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.app.browser.fixture_submit import FixtureSubmitPage
from backend.app.config import DatabaseSettings, ScoringSettings, load_browser_settings, load_database_settings, load_scoring_settings
from backend.app.db import create_database_engine
from backend.app.main import create_app
from backend.app.models.application import Application
from backend.app.models.automation_guard import AutomationGuard
from backend.app.models.job import Job
from backend.app.models.task import Task
from backend.app.runner.profile_lock import browser_lock, ensure_profiles_idle
from backend.app.runner.task_runner import TaskRunner
from backend.app.services import auto


@pytest.fixture
def auto_db():
    settings = load_database_settings(testing=True)
    engine = create_database_engine(settings)
    prefix = f"stage12-{uuid4().hex}-"
    scoring = load_scoring_settings()
    with Session(engine) as session, session.begin():
        guard = session.get(AutomationGuard, "fixture")
        prior_guard = {key: getattr(guard, key) for key in ("blocked_at", "reason_code", "task_id", "acknowledged_at")}
        for key in prior_guard:
            setattr(guard, key, None)

    def job(label, application=None, **overrides):
        source = overrides.get("source", "fixture")
        key = prefix + label
        values = dict(
            source=source, source_job_id=key, identity_key=f"{source}:{key}",
            title=label, company="隔离验收样例", jd_text="Linux 运维", jd_state="complete",
            availability="active", recommended=True, priority=1, score=85, scoring_version=scoring.version,
        )
        with Session(engine) as session, session.begin():
            row = Job(**{**values, **overrides})
            session.add(row)
            session.flush()
            if application:
                session.add(Application(job_id=row.id, status=application, origin="fixture"))
            return row.id

    try:
        yield settings, engine, prefix, job
    finally:
        with Session(engine) as session, session.begin():
            guard = session.get(AutomationGuard, "fixture")
            for key, value in prior_guard.items():
                setattr(guard, key, value)
            session.flush()
            ids = session.scalars(select(Job.id).where(Job.source_job_id.startswith(prefix))).all()
            session.execute(delete(Application).where(Application.job_id.in_(ids)))
            session.execute(delete(Job).where(Job.id.in_(ids)))
            session.execute(delete(Task).where(Task.request_key.startswith(prefix)))
        engine.dispose()


def body(prefix, ids, **params):
    return {
        "mode": "auto", "provider": "fixture", "request_key": prefix + uuid4().hex,
        "params": {"job_ids": ids, **params},
    }


def submit(client, payload):
    response = client.post("/api/tasks", json=payload)
    assert response.status_code == 202, response.json()
    return response.json()["task_id"]


def wait(client, task_id):
    until = monotonic() + 15
    while monotonic() < until:
        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        task = response.json()
        if task["status"] in {"succeeded", "failed", "stopped", "interrupted"}:
            return task
        sleep(0.04)
    raise AssertionError(f"Auto task {task_id} did not terminate")


def application_snapshot(engine):
    with engine.connect() as conn:
        return conn.execute(select(Application.__table__).order_by(Application.id)).all()


def test_preview_is_read_only_and_applies_candidate_boundaries(auto_db):
    settings, engine, prefix, job = auto_db
    older = job("older")
    newer = job("newer", "pending")
    junior = job("junior", priority=3, score=99)
    excluded = {
        job("not-recommended", recommended=False): "NOT_RECOMMENDED",
        job("low", score=20): "SCORE_BELOW_THRESHOLD",
        job("prior-success", "succeeded"): "APPLICATION_SUCCEEDED",
        job("unknown-result", "uncertain"): "APPLICATION_UNCERTAIN",
        job("in-flight", "sending"): "APPLICATION_SENDING",
        job("prior-failure", "failed"): "FAILED_NEEDS_REQUEUE",
        job("inactive", availability="inactive"): "JOB_INACTIVE",
        job("stale", scoring_version="old"): "SCORING_STALE",
        job("incomplete", jd_state="partial"): "JD_INCOMPLETE",
        job("identity", identity_key="unverified"): "IDENTITY_UNVERIFIED",
        job("foreign", source="boss"): "SOURCE_MISMATCH",
        2**64 - 1: "JOB_NOT_FOUND",
    }
    before = application_snapshot(engine)
    ids = [junior, older, newer, newer, *excluded]
    payload = body(prefix, ids, max_jobs=2)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        task_id = submit(client, payload)
        assert submit(client, {**payload, "params": {"job_ids": list(reversed(ids)), "max_jobs": 2, "dry_run": True}}) == task_id
        task = wait(client, task_id)
    assert task["status"] == "succeeded" and task["dry_run"] is True
    progress = task["progress"]
    assert progress["browser_submit_calls"] == 0
    assert [row["job_id"] for row in progress["plan"]] == [newer, older]
    assert {row["job_id"]: row["reason"] for row in progress["skipped_jobs"]} == {**excluded, junior: "MAX_JOBS"}
    assert application_snapshot(engine) == before


def simulation(prefix, ids):
    return body(prefix, ids, dry_run=False, confirm_simulation=True, max_jobs=10)


def client_for(settings, cases):
    return TestClient(create_app(settings, fixture_submit_cases=cases), base_url="http://127.0.0.1")


def test_simulator_rejects_the_runtime_database_and_remote_addresses():
    for settings in (
        None,
        DatabaseSettings("127.0.0.1", 3306, "boss_jobs", "boss_app", "dummy"),
        DatabaseSettings("192.0.2.1", 3306, "boss_jobs_test", "boss_app_test", "dummy"),
    ):
        with pytest.raises(ValueError, match="isolated local test database"):
            create_app(settings, fixture_submit_cases={})


def attempts_for(engine, job_id):
    with Session(engine) as session:
        return session.scalars(select(Application).where(Application.job_id == job_id).order_by(Application.id)).all()


def fixture_guard(client):
    return next(row for row in client.get("/api/settings").json()["guards"] if row["provider"] == "fixture")


def acknowledge(client, guard):
    response = client.post("/api/automation-guard/fixture/acknowledge", json={
        "confirmed": True, "blocked_at": guard["blocked_at"],
    })
    assert response.status_code == 200 and response.json()["state"] == "clear"


def test_simulation_confirms_receipt_reuses_pending_and_preserves_failed_history(auto_db, monkeypatch):
    settings, engine, prefix, job = auto_db
    success = job("success", "pending", score=95)
    rejected = job("rejected", score=90)
    already = job("already")
    pending_id = attempts_for(engine, success)[0].id
    observed_sending = []
    original = FixtureSubmitPage.submit

    def observe(page, should_stop):
        rows = attempts_for(engine, page.job_id)
        assert len([row for row in rows if row.blocking_job_id is not None]) == 1
        sending = [row for row in rows if row.status == "sending"]
        assert len(sending) == 1 and sending[0].task_id
        observed_sending.append(sending[0].id)
        return original(page, should_stop)

    monkeypatch.setattr(FixtureSubmitPage, "submit", observe)
    with client_for(settings, {rejected: "rejected", already: "already"}) as client:
        invalid = client.post("/api/tasks", json=body(prefix, [success], dry_run=False))
        assert invalid.status_code == 422 and invalid.json()["detail"]["code"] == "SIMULATION_CONFIRMATION_REQUIRED"
        result = wait(client, submit(client, simulation(prefix, [already, rejected, success, success])))
        assert result["status"] == "succeeded"
        assert {key: result["progress"][key] for key in ("succeeded", "failed", "uncertain", "browser_submit_calls")} == {
            "succeeded": 2, "failed": 1, "uncertain": 0, "browser_submit_calls": 2,
        }
        [saved] = attempts_for(engine, success)
        assert (saved.id, saved.origin, saved.status, saved.result_code, saved.task_id) == (
            pending_id, "auto", "succeeded", "FIXTURE_RECEIPT", result["task_id"],
        )
        assert f"回执 FIXTURE-{success}" in saved.evidence_summary and saved.resolved_at is not None
        [saved] = attempts_for(engine, already)
        assert saved.status == "succeeded" and saved.result_code == "FIXTURE_ALREADY_SUBMITTED"
        [failed] = attempts_for(engine, rejected)
        assert failed.status == "failed" and failed.result_code == "FIXTURE_REJECTED"
        assert "明确拒绝" in failed.evidence_summary
        assert observed_sending[0] == pending_id and len(observed_sending) == 3

        repeat = wait(client, submit(client, simulation(prefix, [success, rejected, already])))
        assert repeat["progress"]["browser_submit_calls"] == 0
        assert repeat["progress"]["skipped"] == {"APPLICATION_SUCCEEDED": 2, "FAILED_NEEDS_REQUEUE": 1}
        pending = client.post("/api/applications", json={"job_id": rejected})
        assert pending.status_code == 201
        retry = wait(client, submit(client, simulation(prefix, [rejected])))
        assert retry["progress"]["browser_submit_calls"] == 1
        rows = attempts_for(engine, rejected)
        assert [(row.id, row.status) for row in rows] == [(failed.id, "failed"), (pending.json()["id"], "failed")]


def test_submit_rechecks_recommendation_and_prior_success_after_planning(auto_db, monkeypatch):
    settings, engine, prefix, job = auto_db
    changed = job("changed-recommendation")
    success = job("recorded-during-plan")
    original = auto.plan_candidates

    def mutate_after_plan(*args):
        plan = original(*args)
        with Session(engine) as session, session.begin():
            session.get(Job, changed).recommended = False
            session.add(Application(job_id=success, origin="manual", status="succeeded"))
        return plan

    monkeypatch.setattr(auto, "plan_candidates", mutate_after_plan)
    with client_for(settings, {}) as client:
        task = wait(client, submit(client, simulation(prefix, [changed, success])))
    assert task["status"] == "succeeded" and task["progress"]["browser_submit_calls"] == 0
    assert task["progress"]["skipped"] == {"NOT_RECOMMENDED": 1, "APPLICATION_SUCCEEDED": 1}
    assert attempts_for(engine, changed) == []
    assert [row.origin for row in attempts_for(engine, success)] == ["manual"]


def test_submit_rechecks_current_rules_after_planning(auto_db, monkeypatch):
    settings, engine, prefix, job = auto_db
    selected = job("rules-change")
    original = auto.plan_candidates

    def replace_rule_after_plan(*args):
        plan = original(*args)
        scoring = load_scoring_settings()
        monkeypatch.setattr(auto, "load_scoring_settings", lambda: ScoringSettings(
            version="new-rules", document={**scoring.document, "version": "new-rules"},
        ))
        return plan

    monkeypatch.setattr(auto, "plan_candidates", replace_rule_after_plan)
    with client_for(settings, {}) as client:
        task = wait(client, submit(client, simulation(prefix, [selected])))
    assert (task["status"], task["stop_reason"], task["progress"]["browser_submit_calls"]) == ("stopped", "SCORING_CHANGED", 0)
    assert attempts_for(engine, selected) == []


def test_concurrent_auto_admission_and_user_stop_before_click(auto_db, monkeypatch):
    settings, engine, prefix, job = auto_db
    selected = job("selected")
    waiting = Event()
    resume = Event()
    original = FixtureSubmitPage.open

    def hold(page, *args):
        original(page, *args)
        waiting.set()
        assert resume.wait(10)

    monkeypatch.setattr(FixtureSubmitPage, "open", hold)
    payload = simulation(prefix, [selected, selected])
    with client_for(settings, {}) as client:
        try:
            with ThreadPoolExecutor(max_workers=3) as pool:
                responses = list(pool.map(lambda data: client.post("/api/tasks", json=data), [
                    payload, payload, simulation(prefix, [selected]),
                ]))
            assert {response.status_code for response in responses} == {202, 409}
            ids = {response.json()["task_id"] for response in responses if response.status_code == 202}
            assert len(ids) == 1
            task_id = ids.pop()
            assert waiting.wait(10)
            [reserved] = attempts_for(engine, selected)
            assert reserved.status == "sending" and reserved.task_id == task_id
            assert client.post("/api/applications", json={"job_id": selected}).status_code == 409
            assert client.post(f"/api/tasks/{task_id}/stop", json={}).status_code == 200
        finally:
            resume.set()
        task = wait(client, task_id)
    assert task["stop_reason"] == "USER_STOPPED" and task["progress"]["browser_submit_calls"] == 0
    assert [(row.status, row.result_code) for row in attempts_for(engine, selected)] == [("failed", "SUBMIT_CANCELLED")]


@pytest.mark.parametrize(("case", "reason", "action_on_risk"), [
    ("CAPTCHA_REQUIRED", "CAPTCHA_REQUIRED", False),
    ("SECURITY_CHECK", "SECURITY_CHECK", False),
    ("RATE_LIMITED", "RATE_LIMITED", False),
    ("ACCOUNT_ABNORMAL", "ACCOUNT_ABNORMAL", False),
    ("LOGIN_REQUIRED", "LOGIN_REQUIRED", False),
    ("unknown", "PAGE_UNRECOGNIZED", False),
    ("duplicate", "PAGE_UNRECOGNIZED", False),
    ("wrong_identity", "PAGE_UNRECOGNIZED", False),
    ("wrong_receipt", "PAGE_UNRECOGNIZED", True),
    ("post_risk", "SECURITY_CHECK", True),
])
def test_safe_stop_preserves_committed_progress_and_guard_after_restart(auto_db, case, reason, action_on_risk):
    settings, engine, prefix, job = auto_db
    first = job("first", score=95)
    risk = job("risk", score=90)
    later = job("later")
    payload = simulation(prefix, [first, risk, later])
    with client_for(settings, {risk: case}) as client:
        task_id = submit(client, payload)
        result = wait(client, task_id)
        assert (result["status"], result["stop_reason"]) == ("stopped", reason)
        assert result["progress"]["browser_submit_calls"] == 1 + action_on_risk
        guard = fixture_guard(client)
        assert (guard["state"], guard["reason_code"], guard["task_id"]) == ("blocked", reason, task_id)
        assert client.post("/api/tasks", json=simulation(prefix, [later])).status_code == 423
    assert [row.status for row in attempts_for(engine, first)] == ["succeeded"]
    assert [row.status for row in attempts_for(engine, risk)] == ["uncertain" if action_on_risk else "failed"]
    assert attempts_for(engine, later) == []
    browser = load_browser_settings()
    assert not list(browser.profile_root.glob(f"auto-{task_id}-*"))
    with browser_lock():
        ensure_profiles_idle(browser.profile_root)
    with client_for(settings, {}) as restarted:
        assert fixture_guard(restarted) == guard
        review = {"mode": "review", "request_key": prefix + uuid4().hex, "params": {"keywords": ["运维实习生"]}}
        assert restarted.post("/api/tasks", json=review).status_code == 423
        acknowledge(restarted, guard)
        assert wait(restarted, submit(restarted, payload)) == result
        assert attempts_for(engine, later) == []
        fresh = wait(restarted, submit(restarted, body(prefix, [later])))
        assert [row["job_id"] for row in fresh["progress"]["plan"]] == [later]


def test_missing_receipt_blocks_same_job_even_after_guard_acknowledgement(auto_db):
    settings, engine, prefix, job = auto_db
    unknown = job("only-chat", score=95)
    later = job("later")
    with client_for(settings, {unknown: "uncertain"}) as client:
        task = wait(client, submit(client, simulation(prefix, [unknown, later])))
        assert task["status"] == "stopped" and task["stop_reason"] == "SUBMIT_UNCERTAIN"
        assert task["progress"]["browser_submit_calls"] == 1 and attempts_for(engine, later) == []
        [record] = attempts_for(engine, unknown)
        assert record.status == "uncertain" and record.resolved_at is None
        acknowledge(client, fixture_guard(client))
        assert client.post("/api/applications", json={"job_id": unknown}).status_code == 409
        repeat = wait(client, submit(client, simulation(prefix, [unknown])))
        assert repeat["progress"]["browser_submit_calls"] == 0
        assert repeat["progress"]["skipped"] == {"APPLICATION_UNCERTAIN": 1}
        response = client.post(f"/api/applications/{record.id}/resolve", json={
            "status": "succeeded", "evidence_summary": "人工核对样例回执",
        })
        assert response.status_code == 200 and response.json()["status"] == "succeeded"
        assert len(attempts_for(engine, unknown)) == 1


def test_write_outage_retries_ledger_only_and_stops_other_submissions(auto_db, monkeypatch):
    settings, engine, prefix, job = auto_db
    first = job("write-outage", score=95)
    later = job("later")
    settling = Event()
    restore_database = Event()
    outage = OperationalError(None, None, RuntimeError("injected write outage"))
    original_finish = TaskRunner._finish

    def break_result(*args):
        raise outage

    def reject_ledger_until_ready(self, *args, **kwargs):
        if kwargs.get("recover_sending") and not restore_database.is_set():
            settling.set()
            raise outage
        return original_finish(self, *args, **kwargs)

    monkeypatch.setattr(auto, "finish_auto_attempt", break_result)
    monkeypatch.setattr(TaskRunner, "_finish", reject_ledger_until_ready)
    with client_for(settings, {}) as client:
        task_id = submit(client, simulation(prefix, [first, later]))
        try:
            assert settling.wait(10)
            assert [row.status for row in attempts_for(engine, first)] == ["sending"]
            assert client.post("/api/tasks", json=simulation(prefix, [later])).status_code == 409
        finally:
            restore_database.set()
        task = wait(client, task_id)
        assert (task["status"], task["stop_reason"], task["error_code"]) == ("stopped", "SUBMIT_UNCERTAIN", "DATABASE_WRITE_FAILED")
        assert task["progress"]["browser_submit_calls"] == task["progress"]["uncertain"] == 1
        assert fixture_guard(client)["reason_code"] == "SUBMIT_UNCERTAIN"
    assert [row.status for row in attempts_for(engine, first)] == ["uncertain"]
    assert attempts_for(engine, later) == []


def test_interrupted_process_recovers_sending_and_never_replays(auto_db):
    settings, engine, prefix, job = auto_db
    first = job("interrupted", score=95)
    later = job("later")
    script = """
import os
import sys
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from backend.app.config import load_database_settings
from backend.app.main import create_app
from backend.app.runner.task_runner import TaskRunner
from backend.app.services import auto
from backend.tests.test_auto import simulation, submit, wait

def interrupt_write(*args):
    assert args[-1].status == "succeeded"
    raise OperationalError(None, None, RuntimeError("injected exit before ledger write"))

auto.finish_auto_attempt = interrupt_write
# The Playwright context has unwound at this point. Exit before any recovery write.
TaskRunner._settle_auto = lambda *args: os._exit(72)
with TestClient(create_app(load_database_settings(testing=True), fixture_submit_cases={}), base_url="http://127.0.0.1") as client:
    wait(client, submit(client, simulation(sys.argv[1], [int(sys.argv[2]), int(sys.argv[3])])))
"""
    process = run([sys.executable, "-c", script, prefix, str(first), str(later)],
                  capture_output=True, text=True, encoding="utf-8", timeout=30, creationflags=CREATE_NO_WINDOW)
    assert process.returncode == 72, process.stderr
    [reserved] = attempts_for(engine, first)
    assert reserved.status == "sending" and attempts_for(engine, later) == []
    with client_for(settings, {}) as client:
        recovered = wait(client, reserved.task_id)
        assert recovered["status"] == "interrupted" and recovered["stop_reason"] == "PROCESS_RESTART"
        assert recovered["progress"]["uncertain"] == 1
        guard = fixture_guard(client)
        assert (guard["reason_code"], guard["task_id"]) == ("SUBMIT_UNCERTAIN", reserved.task_id)
        assert client.post("/api/tasks", json=simulation(prefix, [first])).status_code == 423
        acknowledge(client, guard)
        repeat = wait(client, submit(client, simulation(prefix, [first])))
        assert repeat["progress"]["browser_submit_calls"] == 0
        assert repeat["progress"]["skipped"] == {"APPLICATION_UNCERTAIN": 1}
    assert [(row.id, row.status, row.result_code) for row in attempts_for(engine, first)] == [
        (reserved.id, "uncertain", "PROCESS_RESTART"),
    ]
    assert attempts_for(engine, later) == []
