"""Tests for /api/connections/notion/oauth/* — "Connect with Notion".

Mounts only the two routers involved. The mnemify.ai broker is faked with
``httpx.MockTransport``; ``MNEMIFY_HOME`` is a tmp dir (conftest), so the
``.env`` and ``mnemify.yaml`` written here are throwaway.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import credential_store, routes_connections, routes_notion_oauth
from src.api.yaml_writer import read_config, upsert_source

FLOW = "flow-abcdef123456"
REAL_ASYNC_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("NOTION_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv(routes_notion_oauth.BROKER_ENV, raising=False)
    routes_notion_oauth._pending.clear()
    routes_notion_oauth._results.clear()
    routes_notion_oauth._result_times.clear()
    yield
    routes_notion_oauth._pending.clear()
    routes_notion_oauth._results.clear()
    routes_notion_oauth._result_times.clear()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_connections.router, prefix="/api")
    app.include_router(routes_notion_oauth.router, prefix="/api")
    with TestClient(app, base_url="http://127.0.0.1:8783", follow_redirects=False) as c:
        yield c


@pytest.fixture
def broker(monkeypatch):
    """Fake the mnemify.ai /token endpoint. Set ``broker.response`` per test."""

    class Broker:
        calls: list[httpx.Request] = []
        response = httpx.Response(
            200,
            json={
                "access_token": "ntn_oauth_token_1234",
                "refresh_token": "nrt_refresh_5678",
                "workspace_name": "Acme HQ",
                "bot_id": "bot-1",
            },
        )

    def handler(request: httpx.Request) -> httpx.Response:
        Broker.calls.append(request)
        if isinstance(Broker.response, Exception):
            raise Broker.response
        return Broker.response

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return REAL_ASYNC_CLIENT(*args, **kwargs)

    Broker.calls = []
    monkeypatch.setattr(routes_notion_oauth.httpx, "AsyncClient", factory)
    return Broker


def _start(client) -> str:
    """Run the authorize step and return the state it minted."""
    r = client.get("/api/connections/notion/oauth/authorize", params={"flow": FLOW})
    assert r.status_code == 302
    loc = urlparse(r.headers["location"])
    assert f"{loc.scheme}://{loc.netloc}{loc.path}" == "https://www.mnemify.ai/api/notion/authorize"
    return parse_qs(loc.query)["state"][0]


def _status(client) -> dict:
    return client.get("/api/connections/notion/oauth/status", params={"flow": FLOW}).json()


# ── authorize ─────────────────────────────────────────────────────

def test_authorize_mints_a_state_carrying_the_bound_port(client):
    state = _start(client)
    port, nonce = state.split(".", 1)
    assert port.isdigit()
    assert len(nonce) >= 32
    assert _status(client) == {"status": "pending"}


def test_authorize_uses_the_broker_override(client, monkeypatch):
    monkeypatch.setenv(routes_notion_oauth.BROKER_ENV, "http://localhost:3000/")
    r = client.get("/api/connections/notion/oauth/authorize", params={"flow": FLOW})
    assert r.headers["location"].startswith("http://localhost:3000/api/notion/authorize?state=")


def test_authorize_rejects_a_malformed_flow_id(client):
    r = client.get("/api/connections/notion/oauth/authorize", params={"flow": "bad id!"})
    assert r.status_code == 400


def test_each_sign_in_gets_a_fresh_state(client):
    assert _start(client) != _start(client)


# ── callback ──────────────────────────────────────────────────────

def test_callback_exchanges_the_code_and_saves_the_connection(client, broker):
    state = _start(client)
    r = client.get("/api/connections/notion/oauth/callback", params={"state": state, "code": "c-1"})
    assert r.status_code == 200
    assert "Notion connected" in r.text

    [call] = broker.calls
    assert str(call.url) == "https://www.mnemify.ai/api/notion/token"
    assert json.loads(call.content) == {"code": "c-1"}

    assert credential_store.get_secret("NOTION_TOKEN") == "ntn_oauth_token_1234"
    assert credential_store.get_secret("NOTION_REFRESH_TOKEN") == "nrt_refresh_5678"
    block = read_config()["sources"]["notion"]
    assert block["enabled"] is True
    assert block["token_env"] == "NOTION_TOKEN"
    assert block["auth"] == "oauth"
    assert block["workspace_name"] == "Acme HQ"
    assert _status(client) == {"status": "connected", "workspace_name": "Acme HQ"}

    [card] = [c for c in client.get("/api/connections").json() if c["source"] == "notion"]
    assert card["status"] == "connected"
    assert card["workspace_name"] == "Acme HQ"


def test_the_token_never_reaches_the_browser(client, broker):
    state = _start(client)
    r = client.get("/api/connections/notion/oauth/callback", params={"state": state, "code": "c-1"})
    assert "ntn_oauth_token_1234" not in r.text
    assert "ntn_oauth_token_1234" not in json.dumps(_status(client))


def test_a_state_works_only_once(client, broker):
    state = _start(client)
    client.get("/api/connections/notion/oauth/callback", params={"state": state, "code": "c-1"})
    again = client.get("/api/connections/notion/oauth/callback", params={"state": state, "code": "c-2"})
    assert again.status_code == 400
    assert len(broker.calls) == 1


def test_an_unknown_state_is_refused_without_calling_the_broker(client, broker):
    r = client.get(
        "/api/connections/notion/oauth/callback",
        params={"state": "8783.attacker-minted-state-xxxxxxxx", "code": "theirs"},
    )
    assert r.status_code == 400
    assert broker.calls == []
    assert credential_store.get_secret("NOTION_TOKEN") is None


def test_an_expired_state_is_refused(client, broker, monkeypatch):
    state = _start(client)
    routes_notion_oauth._pending[state].created -= routes_notion_oauth.FLOW_TTL_SECONDS + 1
    r = client.get("/api/connections/notion/oauth/callback", params={"state": state, "code": "c"})
    assert r.status_code == 400
    assert broker.calls == []
    assert _status(client)["status"] == "error"


def test_cancelled_consent_is_reported(client, broker):
    state = _start(client)
    r = client.get("/api/connections/notion/oauth/callback", params={"state": state, "error": "access_denied"})
    assert "cancelled" in r.text
    assert broker.calls == []
    status = _status(client)
    assert status["status"] == "error"
    assert "cancelled" in status["reason"]


def test_a_broker_error_is_reported_and_nothing_is_saved(client, broker):
    broker.response = httpx.Response(400, json={"error": "invalid_grant"})
    state = _start(client)
    client.get("/api/connections/notion/oauth/callback", params={"state": state, "code": "stale"})
    status = _status(client)
    assert status["status"] == "error"
    assert "invalid_grant" in status["reason"]
    assert credential_store.get_secret("NOTION_TOKEN") is None


def test_an_unreachable_broker_is_reported(client, broker):
    broker.response = httpx.ConnectError("boom")
    state = _start(client)
    client.get("/api/connections/notion/oauth/callback", params={"state": state, "code": "c"})
    assert "Couldn't reach mnemify.ai" in _status(client)["reason"]


def test_reconnecting_keeps_the_existing_scope(client, broker):
    upsert_source("notion", {"enabled": True, "token_env": "NOTION_TOKEN", "scope": ["page-1", "db-2"], "concurrency": 3})
    state = _start(client)
    client.get("/api/connections/notion/oauth/callback", params={"state": state, "code": "c"})
    block = read_config()["sources"]["notion"]
    assert block["scope"] == ["page-1", "db-2"]
    assert block["concurrency"] == 3


def test_scope_can_be_set_after_oauth_without_a_token(client, broker):
    state = _start(client)
    client.get("/api/connections/notion/oauth/callback", params={"state": state, "code": "c"})
    r = client.post("/api/connections/notion/scope", json={"scope": ["page-9"]})
    assert r.status_code == 200
    block = read_config()["sources"]["notion"]
    assert block["scope"] == ["page-9"]
    assert block["auth"] == "oauth"


def test_disconnect_forgets_both_tokens(client, broker):
    state = _start(client)
    client.get("/api/connections/notion/oauth/callback", params={"state": state, "code": "c"})
    client.delete("/api/connections/notion")
    assert credential_store.get_secret("NOTION_TOKEN") is None
    assert credential_store.get_secret("NOTION_REFRESH_TOKEN") is None


def test_pasting_a_token_after_oauth_drops_the_refresh_token(client, broker):
    state = _start(client)
    client.get("/api/connections/notion/oauth/callback", params={"state": state, "code": "c"})
    client.post("/api/connections/notion/save", json={"token": "ntn_internal_9999", "scope": []})
    assert credential_store.get_secret("NOTION_TOKEN") == "ntn_internal_9999"
    assert credential_store.get_secret("NOTION_REFRESH_TOKEN") is None
    assert "auth" not in read_config()["sources"]["notion"]


def test_the_harvester_accepts_the_oauth_source_block(client, broker):
    # The block carries `auth` and `workspace_name`; the plugin factory must
    # not trip over them, and must pick up the OAuth token from the env.
    from src.harvester import notion as _notion  # noqa: F401  (registers the plugin)
    from src.harvester.registry import create_plugin

    state = _start(client)
    client.get("/api/connections/notion/oauth/callback", params={"state": state, "code": "c"})
    plugin, notion_client = create_plugin("notion", dict(read_config()["sources"]["notion"]))
    assert plugin is not None
    assert notion_client.token == "ntn_oauth_token_1234"


def test_settled_results_are_pruned(client, broker):
    state = _start(client)
    client.get("/api/connections/notion/oauth/callback", params={"state": state, "code": "c"})
    routes_notion_oauth._result_times[FLOW] -= routes_notion_oauth.FLOW_TTL_SECONDS + 1
    assert _status(client) == {"status": "unknown"}


def test_status_for_an_unknown_flow(client):
    assert _status(client) == {"status": "unknown"}
