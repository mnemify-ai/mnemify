"""/api/system/* — the process's own lifecycle: heartbeat, quit, and
"show me my data folder"."""

from __future__ import annotations

import logging
import subprocess
import sys

from fastapi import APIRouter, Header, HTTPException, Response

from .. import paths
from . import idle, lifecycle

router = APIRouter()
logger = logging.getLogger(__name__)

#: Any non-empty value ("web" from the UI, "cli" from ``mnemify stop``).
CLIENT_HEADER = "X-Mnemify-Client"


@router.post("/system/heartbeat", status_code=204)
async def heartbeat() -> Response:
    """The open tab saying "a human still has me on screen".

    The middleware already stamped the idle clock for this path; the explicit
    ``touch()`` keeps the endpoint meaningful if the middleware is ever
    mounted differently (and costs nothing).
    """
    idle.touch()
    return Response(status_code=204)


@router.post("/system/shutdown")
async def shutdown(
    x_mnemify_client: str | None = Header(default=None),
) -> dict:
    """Stop the server.

    Guarded by a required custom header rather than a token: a custom header
    forces a CORS preflight, and the app allows no cross-origin requests in a
    normal (non ``--reload``) run — so a random page you have open in another
    tab cannot quit your Mnemify. Localhost callers that mean it (the UI's
    Quit button, ``mnemify stop``) send it trivially.
    """
    if not x_mnemify_client or not x_mnemify_client.strip():
        raise HTTPException(status_code=403, detail=f"{CLIENT_HEADER} header required")
    stopping = lifecycle.request_shutdown("api")
    logger.info("shutdown requested by client %r", x_mnemify_client)
    return {"ok": True, "stopping": stopping}


def _reveal_command(folder: str) -> list[str]:
    """The platform's "open this folder in the file manager" command."""
    if sys.platform == "darwin":
        return ["open", folder]
    if sys.platform.startswith("win"):
        return ["explorer", folder]
    return ["xdg-open", folder]


@router.post("/system/open-home")
async def open_home(
    x_mnemify_client: str | None = Header(default=None),
) -> dict:
    """Open the data home (``paths.home()``) in the OS file manager.

    The browser cannot open a local folder, but the server runs on the same
    machine, so it does it on the tab's behalf. The folder is always
    ``paths.home()`` — nothing from the request is passed to the opener, so
    this can never become a "launch anything" endpoint. Same header guard as
    ``/system/shutdown``, for the same CSRF reason.

    Answers 501 when the platform has no opener (a headless Linux box with no
    ``xdg-open``): the UI then shows the path for the user to copy instead.
    """
    if not x_mnemify_client or not x_mnemify_client.strip():
        raise HTTPException(status_code=403, detail=f"{CLIENT_HEADER} header required")
    folder = str(paths.home())
    paths.ensure_home()
    cmd = _reveal_command(folder)
    try:
        subprocess.Popen(  # noqa: S603 — fixed argv, no shell, no user input
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        logger.warning("could not open %s with %s: %s", folder, cmd[0], exc)
        raise HTTPException(
            status_code=501,
            detail=f"No file manager opener ({cmd[0]}) on this machine. The folder is {folder}",
        ) from exc
    logger.info("opened data home %s for client %r", folder, x_mnemify_client)
    return {"ok": True, "path": folder}
