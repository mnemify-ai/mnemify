"""/api/system/* — the process's own lifecycle: heartbeat and quit."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Response

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
