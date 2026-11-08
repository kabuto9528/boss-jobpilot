import socket

from fastapi.testclient import TestClient
import pytest

from backend.app import config
from backend.app.config import DatabaseConfigError, DatabaseSettings, load_database_settings
from backend.app.main import create_app


def test_health_with_missing_configuration(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        health = client.get("/api/health")
        ready = client.get("/api/ready")

    assert (health.status_code, health.json()) == (200, {"status": "ok"})
    assert (ready.status_code, ready.json()) == (503, {"status": "unavailable"})


def test_health_with_unreachable_mysql():
    # Reserve a local port without listening, so no database can answer it.
    with socket.socket() as socket_guard:
        socket_guard.bind(("127.0.0.1", 0))
        port = socket_guard.getsockname()[1]
        settings = DatabaseSettings("127.0.0.1", port, "boss_jobs_test", "boss_app_test", "fake@:/#pass")
        with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
            ready = client.get("/api/ready")
            health = client.get("/api/health")

    assert (ready.status_code, ready.json()) == (503, {"status": "unavailable"})
    assert (health.status_code, health.json()) == (200, {"status": "ok"})


def test_test_configuration_rejects_runtime_account(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env.test").write_text(
        "DB_HOST=127.0.0.1\nDB_PORT=3306\nDB_NAME=boss_jobs\n"
        "DB_USER=boss_app\nDB_PASSWORD=fake\n",
        encoding="utf-8",
    )

    with pytest.raises(DatabaseConfigError, match=r"\.env\.test"):
        load_database_settings(testing=True)


def test_ready_with_mysql_test_database():
    if not (config.PROJECT_ROOT / ".env.test").is_file():
        pytest.skip("Configure .env.test to verify the isolated MySQL connection.")

    settings = load_database_settings(testing=True)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        ready = client.get("/api/ready")

    assert (ready.status_code, ready.json()) == (200, {"status": "ready"})
