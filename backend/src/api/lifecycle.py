"""The running server's shutdown handle.

``mnemify up`` builds a ``uvicorn.Server`` and registers it here, so anything
inside the app — the idle watchdog, ``POST /api/system/shutdown``, the UI's
Quit button — can ask the process to stop without signals or a process table
lookup. Deliberately tiny and dependency-free: importing this must never drag
in uvicorn (``--reload`` and every ``TestClient`` run have no server to
register, and must keep working).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ``uvicorn.Server`` — typed loosely so this module has no uvicorn import.
_server: Any | None = None


def set_server(server: Any) -> None:
    """Register the ``uvicorn.Server`` that owns this process."""
    global _server
    _server = server


def clear_server() -> None:
    """Forget the registered server (tests; process teardown)."""
    global _server
    _server = None


def has_server() -> bool:
    return _server is not None


def request_shutdown(reason: str) -> bool:
    """Ask the server to exit cleanly. Returns whether a server was there.

    A no-op under ``--reload`` (the reloader supervises a child process) and
    under ``TestClient``, where no ``Server`` is ever registered — log and
    move on rather than raising into a request handler.
    """
    if _server is None:
        logger.info("shutdown requested (%s) but no server is registered — ignoring", reason)
        return False
    logger.info("shutdown requested (%s) — stopping", reason)
    _server.should_exit = True
    return True
