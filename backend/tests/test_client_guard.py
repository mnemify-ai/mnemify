"""``ClientGuardMiddleware``: no state change without ``X-Mnemify-Client``.

The threat is a page on another site making the browser POST to
``http://localhost:8783/api/...`` — Host is ``localhost`` (Host guard passes)
and a body-less POST needs no CORS preflight. The custom header is the one
thing that page cannot add.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.api import create_app


def _foreign_client() -> TestClient:
    """A client with *no* client header — what a cross-site page can send."""
    c = TestClient(create_app())
    del c.headers["X-Mnemify-Client"]
    return c


def test_bodyless_mutations_are_refused_without_the_header(tmp_path):
    c = _foreign_client()
    for path in (
        "/api/reset",
        "/api/harvest/reset",
        "/api/harvest/cancel",
        "/api/terrain/build",
        "/api/terrain/cancel",
        "/api/settings/retention/purge-now",
        "/api/connections/notion/discover",
        "/api/connections/notion/recover-deleted",
        "/api/documents/abc/reharvest",
        "/api/system/heartbeat",
    ):
        r = c.post(path, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403, (path, r.status_code, r.text)
        assert "X-Mnemify-Client" in r.json()["detail"]


def test_put_patch_delete_are_refused_without_the_header(tmp_path):
    c = _foreign_client()
    assert c.put("/api/secrets/OPENAI_API_KEY", json={"value": "sk-x"}).status_code == 403
    assert c.patch("/api/settings/retention", json={}).status_code == 403
    assert c.delete("/api/connections/notion").status_code == 403


def test_an_empty_header_does_not_count(tmp_path):
    c = _foreign_client()
    assert c.post("/api/harvest/cancel", headers={"X-Mnemify-Client": "  "}).status_code == 403


def test_reads_and_sse_stay_open(tmp_path):
    c = _foreign_client()
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/connections").status_code == 200
    assert c.get("/api/documents/stats").status_code in (200, 404)


def test_our_own_clients_pass(tmp_path):
    c = TestClient(create_app())  # conftest gives it the header
    assert c.post("/api/harvest/cancel").status_code == 200
    assert c.post("/api/harvest/cancel", headers={"X-Mnemify-Client": "cli"}).status_code == 200


def test_the_guard_does_not_apply_outside_the_api(tmp_path):
    # The SPA fallback and static files never mutate anything; a POST there
    # is a 404/405 from the app, not a 403 from the guard.
    c = _foreign_client()
    assert c.post("/some/spa/route").status_code != 403


def test_full_reset_needs_the_typed_confirmation(tmp_path):
    c = TestClient(create_app())
    assert c.post("/api/reset").status_code == 422  # body required
    r = c.post("/api/reset", json={"confirm": "reset"})
    assert r.status_code == 400
    assert "RESET" in r.json()["detail"]
    assert c.post("/api/reset", json={"confirm": "RESET"}).json() == {"ok": True}
