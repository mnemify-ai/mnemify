"""/api/connections/notion/oauth/* — "Connect with Notion" via a public integration.

Notion's token exchange needs the integration's client secret, which can't
ship inside a local app. A small broker on mnemify.ai holds it (see
``mnemify-marketing/api/notion/[action].ts``). The flow:

1. The wizard opens ``GET …/oauth/authorize?flow=<id>`` in a new tab. We mint
   ``state = "<port>.<nonce>"``, remember it, and redirect to the broker,
   which redirects to Notion's consent screen.
2. Notion sends the browser to the broker's callback, which redirects the
   browser back here (``…/oauth/callback?code&state``) on 127.0.0.1.
3. We check ``state`` (single use, 10 minutes), then trade the code for a
   token by calling the broker's ``/token`` server-to-server. The token never
   travels through a URL or the browser.
4. The token goes into ``.env`` like a pasted one; the wizard polls
   ``…/oauth/status?flow=<id>`` to learn the outcome.

Pending flows live in memory: a restart mid-sign-in just means "start again".
"""

from __future__ import annotations

import html
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .credential_store import delete_secrets, save_secret
from .yaml_writer import read_config, upsert_source

router = APIRouter()
logger = logging.getLogger(__name__)

BROKER_ENV = "MNEMIFY_AUTH_BROKER"
DEFAULT_BROKER = "https://www.mnemify.ai"
FLOW_TTL_SECONDS = 600

_FLOW_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


@dataclass
class _Flow:
    flow_id: str
    created: float = field(default_factory=time.monotonic)


#: state → pending flow. Popped on first use.
_pending: dict[str, _Flow] = {}
#: flow id → {"status": "pending" | "connected" | "error", ...}, plus the
#: monotonic time it was last written (for pruning).
_results: dict[str, dict[str, Any]] = {}
_result_times: dict[str, float] = {}


def _set_result(flow_id: str, result: dict[str, Any]) -> None:
    _results[flow_id] = result
    _result_times[flow_id] = time.monotonic()


def _broker() -> str:
    return (os.environ.get(BROKER_ENV) or DEFAULT_BROKER).rstrip("/")


def _prune() -> None:
    cutoff = time.monotonic() - FLOW_TTL_SECONDS
    for state, flow in list(_pending.items()):
        if flow.created < cutoff:
            _pending.pop(state, None)
            if _results.get(flow.flow_id, {}).get("status") == "pending":
                _set_result(flow.flow_id, {
                    "status": "error",
                    "reason": "Notion sign-in timed out. Try again.",
                })
    # Settled results only need to outlive the wizard's next poll.
    for flow_id, at in list(_result_times.items()):
        if at < cutoff:
            _results.pop(flow_id, None)
            _result_times.pop(flow_id, None)


def _page(title: str, message: str, *, ok: bool, status_code: int = 200) -> HTMLResponse:
    """The tab the user lands on after Notion. The wizard in the other tab
    picks up the result by polling, so this page only has to say so."""
    color = "#2f7d4f" if ok else "#b3261e"
    # On success, try to close the tab (browsers allow it only for tabs a
    # script opened, which is how the wizard opens this one).
    close = "<script>setTimeout(function(){window.close()},1500)</script>" if ok else ""
    body = f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · Mnemify</title>
<body style="font:15px/1.5 system-ui,sans-serif;max-width:32rem;margin:15vh auto;padding:0 16px">
<h1 style="font-size:20px;color:{color}">{html.escape(title)}</h1>
<p>{html.escape(message)}</p>
<p><a href="/">Back to Mnemify</a></p>
{close}
</body>"""
    return HTMLResponse(body, status_code=status_code, headers={"Cache-Control": "no-store"})


def _save_connection(token_payload: dict[str, Any]) -> str | None:
    """Persist the token and enable the Notion source. Returns the workspace name."""
    access_token = str(token_payload["access_token"]).strip()
    save_secret("NOTION_TOKEN", access_token)
    os.environ["NOTION_TOKEN"] = access_token
    refresh_token = token_payload.get("refresh_token")
    if refresh_token:
        save_secret("NOTION_REFRESH_TOKEN", str(refresh_token).strip())
    else:
        delete_secrets(["NOTION_REFRESH_TOKEN"])

    workspace = token_payload.get("workspace_name") or None
    existing = read_config().get("sources", {}).get("notion", {}) or {}
    block: dict[str, Any] = {
        "enabled": True,
        "token_env": "NOTION_TOKEN",
        "concurrency": existing.get("concurrency", 5),
        "auth": "oauth",
    }
    if workspace:
        block["workspace_name"] = str(workspace)
    # A reconnect keeps what the user already picked; the wizard's scope
    # step (POST /connections/notion/scope) refines it afterwards.
    if existing.get("scope"):
        block["scope"] = list(existing["scope"])
    upsert_source("notion", block)
    return workspace


@router.get("/connections/notion/oauth/authorize")
async def notion_oauth_authorize(request: Request, flow: str):
    if not _FLOW_ID_RE.match(flow):
        raise HTTPException(400, "invalid flow id")
    _prune()
    # The port this server is actually bound to — `mnemify up` falls forward
    # past 8783 when it's taken, and in dev the UI reaches us via Vite's proxy.
    server = request.scope.get("server") or (None, None)
    port = server[1] or request.url.port
    if not port:
        raise HTTPException(500, "can't determine the local port")
    state = f"{port}.{secrets.token_urlsafe(32)}"
    _pending[state] = _Flow(flow_id=flow)
    _set_result(flow, {"status": "pending"})
    return RedirectResponse(
        f"{_broker()}/api/notion/authorize?{urlencode({'state': state})}",
        status_code=302,
    )


@router.get("/connections/notion/oauth/callback")
async def notion_oauth_callback(
    state: str = "",
    code: str | None = None,
    error: str | None = None,
):
    _prune()
    flow = _pending.pop(state, None)
    if flow is None:
        return _page(
            "This sign-in link has expired",
            "It was already used, or it's more than 10 minutes old. Start again from Mnemify.",
            ok=False,
            status_code=400,
        )

    def fail(reason: str) -> HTMLResponse:
        _set_result(flow.flow_id, {"status": "error", "reason": reason})
        return _page("Notion wasn't connected", reason, ok=False)

    if error or not code:
        if error == "access_denied":
            return fail("You cancelled the Notion sign-in. Nothing was connected.")
        return fail(f"Notion returned an error ({error or 'no code'}). Try again.")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{_broker()}/api/notion/token", json={"code": code})
    except httpx.HTTPError as exc:
        logger.warning("notion oauth: broker unreachable: %s", exc.__class__.__name__)
        return fail("Couldn't reach mnemify.ai to finish sign-in. Check your connection and try again.")

    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    if resp.status_code != 200 or not payload.get("access_token"):
        detail = payload.get("error_description") or payload.get("error") or f"HTTP {resp.status_code}"
        logger.warning("notion oauth: token exchange failed: %s", detail)
        return fail(f"Notion didn't accept the sign-in ({detail}). Try again.")

    try:
        workspace = _save_connection(payload)
    except (OSError, ValueError) as exc:
        logger.exception("notion oauth: saving the connection failed")
        return fail(f"Signed in, but saving the connection failed: {exc}")

    _set_result(flow.flow_id, {"status": "connected", "workspace_name": workspace})
    return _page(
        "Notion connected",
        f"Mnemify can now read {workspace or 'your workspace'}. You can close this tab and return to Mnemify.",
        ok=True,
    )


@router.get("/connections/notion/oauth/status")
async def notion_oauth_status(flow: str):
    _prune()
    return _results.get(flow, {"status": "unknown"})
