"""The idle watchdog: which paths count, what blocks a shutdown, and the
in-flight ``/api/ask`` counter.

Everything here is decided by pure functions, so nothing sleeps.
"""

from __future__ import annotations

import asyncio

import pytest

from src.api import idle

TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture(autouse=True)
def _clean_idle():
    idle.reset_for_tests()
    yield
    idle.reset_for_tests()


FLAGS = {
    "compile_running": False,
    "harvest_running": False,
    "ask_in_flight_count": 0,
    "schedules_enabled": False,
}


# ─── should_shutdown ────────────────────────────────────────────────

def test_shuts_down_once_the_window_has_passed():
    assert idle.should_shutdown(1000.0, 1000.0 - 31 * 60, 30, **FLAGS) is True


def test_stays_up_inside_the_window():
    assert idle.should_shutdown(1000.0, 1000.0 - 29 * 60, 30, **FLAGS) is False


def test_exactly_at_the_boundary_shuts_down():
    assert idle.should_shutdown(1000.0, 1000.0 - 30 * 60, 30, **FLAGS) is True


@pytest.mark.parametrize("timeout", [0, -1])
def test_zero_or_negative_timeout_means_never(timeout):
    assert idle.should_shutdown(1e9, 0.0, timeout, **FLAGS) is False


@pytest.mark.parametrize(
    "blocker",
    [
        {"compile_running": True},
        {"harvest_running": True},
        {"ask_in_flight_count": 1},
        {"schedules_enabled": True},
    ],
)
def test_in_flight_work_and_schedules_block_the_shutdown(blocker):
    flags = {**FLAGS, **blocker}
    # Idle for a week — still refuses, because something is running.
    assert idle.should_shutdown(1e6, 0.0, 30, **flags) is False


# ─── which paths count as activity ──────────────────────────────────

@pytest.mark.parametrize(
    "path,expected",
    [
        ("/api/connections", True),
        ("/api/system/heartbeat", True),  # the whole point of the heartbeat
        ("/api/ask", True),
        ("/api/terrain", True),
        ("/api/health", False),  # launcher / single-instance probe
        ("/api/harvest/stream", False),  # EventSource reconnects forever
        ("/api/terrain/stream", False),
        ("/", False),
        ("/assets/index.js", False),
    ],
)
def test_counts_as_activity(path, expected):
    assert idle.counts_as_activity(path) is expected


# ─── the middleware ─────────────────────────────────────────────────

def _app():
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(idle.IdleMiddleware)

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/connections")
    async def connections():
        return []

    @app.get("/api/harvest/stream")
    async def stream():
        return {"sse": True}

    @app.post("/api/ask")
    async def ask():
        # The count must be visible *while* the request runs.
        return {"in_flight": idle.ask_in_flight()}

    return app


def test_middleware_stamps_real_requests_but_not_health_or_sse():
    client = TestClient(_app())

    idle.touch(100.0)
    client.get("/api/health")
    assert idle.last_activity() == 100.0

    idle.touch(100.0)
    client.get("/api/harvest/stream")
    assert idle.last_activity() == 100.0

    idle.touch(100.0)
    client.get("/api/connections")
    assert idle.last_activity() != 100.0


def test_ask_requests_are_counted_while_in_flight_and_released_after():
    client = TestClient(_app())
    assert idle.ask_in_flight() == 0
    resp = client.post("/api/ask")
    assert resp.json() == {"in_flight": 1}
    assert idle.ask_in_flight() == 0


def test_ask_counter_is_released_when_the_handler_raises():
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(idle.IdleMiddleware)

    @app.post("/api/ask")
    async def boom():
        raise ValueError("nope")

    client = TestClient(app, raise_server_exceptions=False)
    client.post("/api/ask")
    assert idle.ask_in_flight() == 0


# ─── check_once (the tick) ──────────────────────────────────────────

def _stub(
    monkeypatch, *, timeout=30.0, schedules=False, compile_=False, harvest=False, server=True
):
    monkeypatch.setattr("src.api.lifecycle.has_server", lambda: server)
    monkeypatch.setattr(idle, "_timeout_minutes", lambda: timeout)
    monkeypatch.setattr(idle, "_schedules_enabled", lambda: schedules)
    monkeypatch.setattr(idle, "_running_flags", lambda: (compile_, harvest))
    asked: list[str] = []
    monkeypatch.setattr(
        "src.api.lifecycle.request_shutdown", lambda reason: asked.append(reason) or True
    )
    return asked


def test_check_once_requests_shutdown_when_idle(monkeypatch):
    asked = _stub(monkeypatch)
    idle.touch(0.0)
    assert idle.check_once(now=31 * 60) is True
    assert asked == ["idle"]


def test_check_once_does_nothing_before_the_window(monkeypatch):
    asked = _stub(monkeypatch)
    idle.touch(0.0)
    assert idle.check_once(now=10 * 60) is False
    assert asked == []


def test_check_once_is_disabled_by_a_zero_timeout(monkeypatch):
    asked = _stub(monkeypatch, timeout=0)
    idle.touch(0.0)
    assert idle.check_once(now=10**6) is False
    assert asked == []


def test_check_once_is_suppressed_by_an_enabled_schedule(monkeypatch, caplog):
    asked = _stub(monkeypatch, schedules=True)
    idle.touch(0.0)
    assert idle.check_once(now=31 * 60) is False
    assert idle.check_once(now=32 * 60) is False
    assert asked == []


@pytest.mark.parametrize("blocker", [{"compile_": True}, {"harvest": True}])
def test_check_once_never_kills_a_running_job(monkeypatch, blocker):
    asked = _stub(monkeypatch, **blocker)
    idle.touch(0.0)
    assert idle.check_once(now=31 * 60) is False
    assert asked == []


def test_check_once_never_kills_an_in_flight_ask(monkeypatch):
    asked = _stub(monkeypatch)
    idle.touch(0.0)
    idle._ask_in_flight = 1
    try:
        assert idle.check_once(now=31 * 60) is False
    finally:
        idle._ask_in_flight = 0
    assert asked == []


# ─── the loop ───────────────────────────────────────────────────────

async def test_watchdog_loop_ticks_on_the_injected_clock(monkeypatch):
    ticks = []
    monkeypatch.setattr(idle, "check_once", lambda: ticks.append(1))

    async def fake_sleep(_seconds):
        if len(ticks) >= 3:
            raise asyncio.CancelledError
        await asyncio.sleep(0)

    with pytest.raises(asyncio.CancelledError):
        await idle.watchdog_loop(interval=999, sleep=fake_sleep)
    assert len(ticks) == 3


async def test_watchdog_loop_survives_a_failing_tick(monkeypatch):
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("settings unreadable")

    monkeypatch.setattr(idle, "check_once", boom)

    async def fake_sleep(_seconds):
        if len(calls) >= 2:
            raise asyncio.CancelledError
        await asyncio.sleep(0)

    with pytest.raises(asyncio.CancelledError):
        await idle.watchdog_loop(interval=999, sleep=fake_sleep)
    assert len(calls) == 2


async def test_start_and_stop_are_clean():
    task = idle.start(interval=999)
    await idle.stop(task)
    assert task.cancelled() or task.done()
    # Stopping "no task" is allowed (the lifespan may never have started one).
    await idle.stop(None)


def test_check_once_without_a_registered_server_skips_and_logs_once(monkeypatch, caplog):
    import logging

    asked = _stub(monkeypatch, server=False)
    idle.touch(0.0)
    logging.disable(logging.NOTSET)
    with caplog.at_level(logging.INFO, logger="src.api.idle"):
        # Way past the window, tick after tick: never asks, never spams.
        assert idle.check_once(now=31 * 60) is False
        assert idle.check_once(now=32 * 60) is False
        assert idle.check_once(now=10**6) is False
    assert asked == []
    notices = [r for r in caplog.records if "no server registered" in r.getMessage()]
    assert len(notices) == 1
    assert notices[0].levelno == logging.INFO


def test_check_once_asks_again_once_a_server_is_registered(monkeypatch):
    from src.api import lifecycle

    asked = _stub(monkeypatch, server=False)
    idle.touch(0.0)
    assert idle.check_once(now=31 * 60) is False
    monkeypatch.setattr(lifecycle, "has_server", lambda: True)
    assert idle.check_once(now=31 * 60) is True
    assert asked == ["idle"]
