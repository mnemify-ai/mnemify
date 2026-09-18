"""/api/system/* — heartbeat + shutdown — and /api/settings/server."""

from __future__ import annotations

import pytest

from src.api import idle, lifecycle

TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture(autouse=True)
def _clean():
    lifecycle.clear_server()
    idle.reset_for_tests()
    yield
    lifecycle.clear_server()
    idle.reset_for_tests()


def _client() -> TestClient:
    """A minimal app with just the system router — no lifespan, no scheduler."""
    from fastapi import FastAPI

    from src.api import routes_system

    app = FastAPI()
    app.add_middleware(idle.IdleMiddleware)
    app.include_router(routes_system.router, prefix="/api")
    return TestClient(app)


class _FakeServer:
    should_exit = False


# ─── heartbeat ──────────────────────────────────────────────────────

def test_heartbeat_returns_204_and_stamps_the_idle_clock():
    client = _client()
    idle.touch(0.0)
    resp = client.post("/api/system/heartbeat")
    assert resp.status_code == 204
    assert resp.content == b""
    assert idle.last_activity() != 0.0


# ─── shutdown ───────────────────────────────────────────────────────

def test_shutdown_without_the_client_header_is_forbidden():
    server = _FakeServer()
    lifecycle.set_server(server)
    resp = _client().post("/api/system/shutdown")
    assert resp.status_code == 403
    assert "X-Mnemify-Client" in resp.json()["detail"]
    assert server.should_exit is False


def test_shutdown_with_an_empty_client_header_is_forbidden():
    server = _FakeServer()
    lifecycle.set_server(server)
    resp = _client().post("/api/system/shutdown", headers={"X-Mnemify-Client": "  "})
    assert resp.status_code == 403
    assert server.should_exit is False


@pytest.mark.parametrize("client_name", ["web", "cli"])
def test_shutdown_with_the_header_stops_the_server(client_name):
    server = _FakeServer()
    lifecycle.set_server(server)
    resp = _client().post("/api/system/shutdown", headers={"X-Mnemify-Client": client_name})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "stopping": True}
    assert server.should_exit is True


def test_shutdown_is_a_noop_when_no_server_is_registered():
    # `--reload` and TestClient runs: report success, stop nothing, never raise.
    resp = _client().post("/api/system/shutdown", headers={"X-Mnemify-Client": "cli"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "stopping": False}


# ─── /api/settings/server ───────────────────────────────────────────

def _settings_client() -> TestClient:
    from fastapi import FastAPI

    from src.api import routes_settings

    app = FastAPI()
    app.include_router(routes_settings.router, prefix="/api")
    return TestClient(app)


def test_server_settings_default_to_30_minutes(tmp_path):
    resp = _settings_client().get("/api/settings/server")
    assert resp.status_code == 200
    assert resp.json() == {"idle_timeout_minutes": 30}


def test_patch_server_settings_round_trips_through_yaml(tmp_path):
    client = _settings_client()
    resp = client.patch("/api/settings/server", json={"idle_timeout_minutes": 5})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "idle_timeout_minutes": 5}
    assert client.get("/api/settings/server").json() == {"idle_timeout_minutes": 5}

    from src import paths

    assert "server:" in paths.yaml_file().read_text(encoding="utf-8")


def test_patch_server_settings_accepts_zero_as_never(tmp_path):
    client = _settings_client()
    assert client.patch("/api/settings/server", json={"idle_timeout_minutes": 0}).status_code == 200
    assert client.get("/api/settings/server").json() == {"idle_timeout_minutes": 0}


@pytest.mark.parametrize("bad", [-1, 100_000, "thirty"])
def test_patch_server_settings_rejects_nonsense(tmp_path, bad):
    resp = _settings_client().patch("/api/settings/server", json={"idle_timeout_minutes": bad})
    assert resp.status_code == 422


def test_patch_server_settings_preserves_other_yaml_blocks(tmp_path):
    from src import paths
    from src.api.yaml_writer import read_config

    paths.ensure_home()
    paths.yaml_file().write_text(
        "raw_root: .mnemify/raw\n"
        "sources:\n"
        "  notion:\n"
        "    enabled: true\n"
        "compile:\n"
        "  ai_mode: local\n",
        encoding="utf-8",
    )
    _settings_client().patch("/api/settings/server", json={"idle_timeout_minutes": 7})
    cfg = read_config()
    assert cfg["sources"]["notion"]["enabled"] is True
    assert cfg["compile"]["ai_mode"] == "local"
    assert cfg["server"]["idle_timeout_minutes"] == 7


def test_malformed_server_block_falls_back_to_the_default(tmp_path):
    from src import paths
    from src.api.routes_settings import server_settings

    paths.ensure_home()
    paths.yaml_file().write_text("server:\n  idle_timeout_minutes: maybe\n", encoding="utf-8")
    assert server_settings() == {"idle_timeout_minutes": 30}


# ─── the idle watchdog reads the persisted value ────────────────────

def test_idle_reads_the_timeout_from_settings(tmp_path):
    from src.api.routes_settings import server_settings

    _settings_client().patch("/api/settings/server", json={"idle_timeout_minutes": 1})
    assert server_settings()["idle_timeout_minutes"] == 1
    assert idle._timeout_minutes() == 1.0


# ─── the flags the watchdog consults ────────────────────────────────

def test_orchestrator_is_running_flags_follow_state():
    from src.api import compile_orchestrator, orchestrator

    assert compile_orchestrator.is_running() is False
    assert orchestrator.is_running() is False
    compile_orchestrator.state.status = "running"
    orchestrator.state.status = "running"
    try:
        assert compile_orchestrator.is_running() is True
        assert orchestrator.is_running() is True
    finally:
        compile_orchestrator.state.status = "idle"
        orchestrator.state.status = "idle"


def test_has_enabled_schedules(tmp_path):
    from src import paths
    from src.api import scheduler

    assert scheduler.has_enabled_schedules() is False

    paths.ensure_home()
    paths.yaml_file().write_text(
        "schedules:\n  notion:\n    cron: '0 3 * * *'\n    enabled: false\n", encoding="utf-8"
    )
    assert scheduler.has_enabled_schedules() is False

    paths.yaml_file().write_text(
        "schedules:\n  notion:\n    cron: '0 3 * * *'\n    enabled: true\n", encoding="utf-8"
    )
    assert scheduler.has_enabled_schedules() is True


# ─── /api/health ────────────────────────────────────────────────────

def test_health_reports_version_commit_platform_and_paths(tmp_path, monkeypatch):
    import sys

    from src import __version__
    from src.api import create_app

    monkeypatch.chdir(tmp_path)
    with TestClient(create_app()) as client:
        body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["version"] == __version__
    assert body["platform"] == sys.platform
    assert body["paths"]["home"] == str(tmp_path)
    # commit is a short sha in a checkout, None when .git is absent.
    assert body["commit"] is None or len(body["commit"]) >= 7
