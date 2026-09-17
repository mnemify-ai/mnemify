"""Idle watchdog — quit the server when nobody is using it.

Mnemify is a local app started by a desktop icon: leaving a forgotten uvicorn
running forever is worse than restarting it. So we track *real* activity and
exit cleanly once there has been none for ``server.idle_timeout_minutes``
(Settings → General, 0 = never).

What counts as activity
    Every ``/api/*`` request, **except**:

    * ``/api/health`` — the launcher and the `mnemify up` single-instance
      check poll it; a health probe is not a user.
    * ``/api/harvest/stream`` and ``/api/terrain/stream`` — an abandoned tab's
      ``EventSource`` reconnects forever, so counting them would pin the
      server up for as long as the browser is open.

    ``/api/system/heartbeat`` *does* count: it is the open tab saying "a human
    still has me on screen", and the frontend only sends it while the document
    is visible. It beats every **30 s** (``useHeartbeat.HEARTBEAT_INTERVAL_MS``)
    — half :data:`DEFAULT_CHECK_INTERVAL_S`, because this loop compares
    ``idle >= timeout``: an equal-period beat can land just after a tick reads
    the clock and lose the race at a 1-minute timeout.

What blocks a shutdown
    A running compile, a running harvest, an in-flight ``/api/ask`` (chat
    streams can outlive the idle window on their own), and — the rule from the
    design — **any enabled harvest schedule**. A scheduler that kills its own
    host is useless, so idle shutdown is suspended entirely while one exists.

Nothing here imports the orchestrators, the scheduler or the settings routes
at module scope: those imports happen inside the watchdog tick. That keeps
:func:`should_shutdown` a pure function (unit-tested without sleeping) and
leaves the orchestrator modules free to import this one.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

#: Polled by launchers/health checks, not humans.
HEALTH_PATH = "/api/health"
#: Server-sent-event endpoints an idle browser tab reconnects to forever.
SSE_PATHS = ("/api/harvest/stream", "/api/terrain/stream")
#: Requests under this prefix are counted as "in flight" until they finish.
ASK_PREFIX = "/api/ask"

#: How often the watchdog wakes. The browser beats twice this often — see the
#: module docstring for why the two periods must not be equal.
DEFAULT_CHECK_INTERVAL_S = 60.0

_last_activity: float = time.monotonic()
_ask_in_flight: int = 0
_schedule_suppression_logged = False


# ─── Activity tracking ──────────────────────────────────────────────

def touch(now: float | None = None) -> None:
    """Stamp "something happened just now"."""
    global _last_activity
    _last_activity = time.monotonic() if now is None else now


def last_activity() -> float:
    return _last_activity


def seconds_idle(now: float | None = None) -> float:
    return (time.monotonic() if now is None else now) - _last_activity


def ask_in_flight() -> int:
    return _ask_in_flight


def counts_as_activity(path: str) -> bool:
    """Whether a request path should reset the idle clock."""
    if not path.startswith("/api"):
        return False
    if path == HEALTH_PATH:
        return False
    return path not in SSE_PATHS


def _is_ask(path: str) -> bool:
    return path == ASK_PREFIX or path.startswith(ASK_PREFIX + "/")


class IdleMiddleware:
    """Pure-ASGI activity stamp.

    Pure ASGI rather than ``BaseHTTPMiddleware`` on purpose: the latter pumps
    the response through an anyio memory stream, which breaks SSE latency for
    ``/api/harvest/stream`` and the ``/api/ask`` token stream.

    Starlette awaits a streaming response's body iterator to completion inside
    the downstream ``app`` call, so the ``finally`` below really does span a
    whole SSE/chat stream — that is what makes the ``/api/ask`` in-flight
    counter correct without wrapping ``send``.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        global _ask_in_flight
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "") or ""
        counted = counts_as_activity(path)
        ask = counted and _is_ask(path)

        if counted:
            touch()
        if ask:
            _ask_in_flight += 1
        try:
            await self.app(scope, receive, send)
        finally:
            if ask:
                _ask_in_flight = max(0, _ask_in_flight - 1)
            if counted:
                touch()


# ─── The decision ───────────────────────────────────────────────────

def should_shutdown(
    now: float,
    last: float,
    timeout_minutes: float,
    *,
    compile_running: bool,
    harvest_running: bool,
    ask_in_flight_count: int,
    schedules_enabled: bool,
) -> bool:
    """Pure predicate: may the server quit itself right now?

    ``timeout_minutes`` <= 0 means "never idle-shutdown".
    """
    if timeout_minutes <= 0:
        return False
    if compile_running or harvest_running or ask_in_flight_count > 0:
        return False
    if schedules_enabled:
        return False
    return (now - last) >= timeout_minutes * 60.0


def _timeout_minutes() -> float:
    from .routes_settings import server_settings

    return float(server_settings()["idle_timeout_minutes"])


def _schedules_enabled() -> bool:
    from . import scheduler

    return scheduler.has_enabled_schedules()


def _running_flags() -> tuple[bool, bool]:
    from . import compile_orchestrator, orchestrator

    return compile_orchestrator.is_running(), orchestrator.is_running()


def check_once(now: float | None = None) -> bool:
    """One watchdog tick. Requests a shutdown and returns whether it did."""
    global _schedule_suppression_logged
    timeout = _timeout_minutes()
    if timeout <= 0:
        return False

    now = time.monotonic() if now is None else now
    if (now - _last_activity) < timeout * 60.0:
        return False

    schedules = _schedules_enabled()
    if schedules:
        if not _schedule_suppression_logged:
            logger.info(
                "idle: %.0f min with no activity, but a harvest schedule is enabled — "
                "staying up (Settings → Schedules)",
                (now - _last_activity) / 60.0,
            )
            _schedule_suppression_logged = True
        return False
    _schedule_suppression_logged = False

    compile_running, harvest_running = _running_flags()
    if not should_shutdown(
        now,
        _last_activity,
        timeout,
        compile_running=compile_running,
        harvest_running=harvest_running,
        ask_in_flight_count=_ask_in_flight,
        schedules_enabled=False,
    ):
        return False

    from . import lifecycle

    logger.info("idle: no activity for %.0f min — shutting down", (now - _last_activity) / 60.0)
    lifecycle.request_shutdown("idle")
    return True


# ─── The background task ────────────────────────────────────────────

async def watchdog_loop(
    *,
    interval: float = DEFAULT_CHECK_INTERVAL_S,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Check every ``interval`` seconds until cancelled."""
    while True:
        await sleep(interval)
        try:
            check_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # a watchdog that dies stops watching — never propagate
            logger.exception("idle: watchdog tick failed")


def start(interval: float = DEFAULT_CHECK_INTERVAL_S) -> asyncio.Task:
    """Reset the clock and start the watchdog. Returns the task to cancel."""
    global _schedule_suppression_logged
    touch()
    _schedule_suppression_logged = False
    return asyncio.create_task(watchdog_loop(interval=interval))


async def stop(task: asyncio.Task | None) -> None:
    """Cancel the watchdog task and wait for it, swallowing the cancellation."""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.debug("idle: watchdog raised on shutdown", exc_info=True)


def reset_for_tests() -> None:
    """Return module state to a clean slate (tests only)."""
    global _ask_in_flight, _schedule_suppression_logged
    _ask_in_flight = 0
    _schedule_suppression_logged = False
    touch()
