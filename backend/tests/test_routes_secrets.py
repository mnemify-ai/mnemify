"""Tests for /api/secrets — the server-side key panel.

The app under test mounts only ``routes_secrets``; building the whole app via
``create_app()`` would drag in the scheduler, the SSE buses and the terrain
store for a router that touches none of them.

``MNEMIFY_HOME`` is redirected to ``tmp_path`` by an autouse fixture in
conftest.py, so every ``.env`` written here lands in a throwaway directory and
never near the developer's real credentials. A second autouse fixture there
(``_no_ambient_secrets``) keeps the allowlisted names out of ``os.environ``
before and after each test, so a saved key can neither come from the
developer's shell nor leak into the rest of the session.
"""

from __future__ import annotations

import os
import stat

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import paths
from src.api import credential_store, routes_secrets

ALLOWLIST = list(routes_secrets.SECRET_ALLOWLIST)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_secrets.router, prefix="/api")
    with TestClient(app) as c:
        yield c


def _row(payload: list[dict], name: str) -> dict:
    return next(r for r in payload if r["name"] == name)


# ── GET /api/secrets ──────────────────────────────────────────────

def test_get_lists_every_allowlisted_name_with_set_false(client):
    rows = client.get("/api/secrets").json()
    assert [r["name"] for r in rows] == ALLOWLIST
    for r in rows:
        assert r["set"] is False
        assert r["hint"] is None
        assert r["label"] and r["kind"]


def test_get_reports_a_saved_key_as_set_with_a_masked_hint(client):
    client.put("/api/secrets/OPENAI_API_KEY", json={"value": "sk-test-abcdefgh-k3Fq"})
    row = _row(client.get("/api/secrets").json(), "OPENAI_API_KEY")
    assert row["set"] is True
    assert row["hint"] == "…k3Fq"


def test_get_never_returns_the_value_anywhere_in_the_body(client):
    secret = "sk-do-not-leak-me-0001"
    client.put("/api/secrets/OPENAI_API_KEY", json={"value": secret})
    body = client.get("/api/secrets").text
    assert secret not in body
    assert "do-not-leak" not in body


def test_get_falls_back_to_the_process_environment(client, monkeypatch):
    # A key exported in the shell (or by a launcher) still shows as set, so
    # the UI doesn't invite the user to re-enter something already working.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-the-shell-9xyz")
    row = _row(client.get("/api/secrets").json(), "ANTHROPIC_API_KEY")
    assert row["set"] is True
    assert row["hint"] == "…9xyz"


# ── PUT /api/secrets/{name} ───────────────────────────────────────

def test_put_persists_to_the_env_file_and_returns_the_row(client):
    resp = client.put("/api/secrets/NOTION_TOKEN", json={"value": "ntn_secret_wxyz"})
    assert resp.status_code == 200
    assert resp.json() == {
        "name": "NOTION_TOKEN",
        "label": routes_secrets.SECRET_ALLOWLIST["NOTION_TOKEN"].label,
        "kind": "token",
        "provider": "notion",
        "testable": False,
        "set": True,
        "hint": "…wxyz",
    }
    assert "NOTION_TOKEN=ntn_secret_wxyz" in paths.env_file().read_text()


def test_put_makes_the_env_file_owner_only(client):
    client.put("/api/secrets/NOTION_TOKEN", json={"value": "ntn_secret_wxyz"})
    mode = stat.S_IMODE(paths.env_file().stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_put_refreshes_the_running_process(client):
    client.put("/api/secrets/OPENAI_API_KEY", json={"value": "sk-live-now-1234"})
    # The compile/harvest code reads os.environ, not the file — a saved key
    # has to be usable without restarting the server.
    assert os.environ["OPENAI_API_KEY"] == "sk-live-now-1234"


def test_put_strips_surrounding_whitespace(client):
    row = client.put("/api/secrets/NOTION_TOKEN", json={"value": "  ntn_padded_abcd \n"}).json()
    assert row["hint"] == "…abcd"
    assert "NOTION_TOKEN=ntn_padded_abcd" in paths.env_file().read_text()


def test_put_preserves_unrelated_lines(client):
    env = paths.env_file()
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text("# hand-written comment\nSOMETHING_ELSE=keep-me\n")
    client.put("/api/secrets/NOTION_TOKEN", json={"value": "ntn_secret_wxyz"})
    text = env.read_text()
    assert "# hand-written comment" in text
    assert "SOMETHING_ELSE=keep-me" in text


@pytest.mark.parametrize("value", ["", "   ", "\n\t "])
def test_put_rejects_an_empty_value(client, value):
    assert client.put("/api/secrets/OPENAI_API_KEY", json={"value": value}).status_code == 400


def test_put_rejects_non_ascii(client):
    # Smart quotes from a styled doc make httpx raise UnicodeEncodeError deep
    # in the request — catch it at the door with a reason the user can act on.
    resp = client.put("/api/secrets/OPENAI_API_KEY", json={"value": "sk-“curly”-key"})
    assert resp.status_code == 400
    assert "non-ASCII" in resp.json()["detail"]
    assert not paths.env_file().exists()


def test_put_rejects_a_name_outside_the_allowlist(client):
    resp = client.put("/api/secrets/AWS_SECRET_ACCESS_KEY", json={"value": "nope"})
    assert resp.status_code == 400
    assert not paths.env_file().exists()


def test_put_cannot_be_used_to_edit_arbitrary_env_keys(client):
    for name in ("PATH", "MNEMIFY_HOME", "path", "notion_token"):
        assert client.put(f"/api/secrets/{name}", json={"value": "x"}).status_code == 400


# ── DELETE /api/secrets/{name} ────────────────────────────────────

def test_delete_removes_the_key_and_returns_204(client):
    client.put("/api/secrets/NOTION_TOKEN", json={"value": "ntn_secret_wxyz"})
    assert client.delete("/api/secrets/NOTION_TOKEN").status_code == 204
    assert _row(client.get("/api/secrets").json(), "NOTION_TOKEN")["set"] is False
    assert "NOTION_TOKEN" not in paths.env_file().read_text()


def test_delete_is_idempotent_on_an_unset_key(client):
    assert client.delete("/api/secrets/NOTION_TOKEN").status_code == 204


def test_delete_404s_outside_the_allowlist(client):
    assert client.delete("/api/secrets/PATH").status_code == 404


def test_delete_leaves_other_secrets_alone(client):
    client.put("/api/secrets/NOTION_TOKEN", json={"value": "ntn_secret_wxyz"})
    client.put("/api/secrets/OPENAI_API_KEY", json={"value": "sk-keep-me-5678"})
    client.delete("/api/secrets/NOTION_TOKEN")
    assert _row(client.get("/api/secrets").json(), "OPENAI_API_KEY")["set"] is True


# ── POST /api/secrets/{name}/test ─────────────────────────────────

def test_test_rejects_a_non_testable_secret(client):
    resp = client.post("/api/secrets/NOTION_TOKEN/test")
    assert resp.status_code == 400
    assert "not testable" in resp.json()["detail"]


def test_test_404s_outside_the_allowlist(client):
    assert client.post("/api/secrets/PATH/test").status_code == 404


def test_test_without_a_saved_key_is_a_reason_not_an_error(client):
    resp = client.post("/api/secrets/OPENAI_API_KEY/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert "No key saved" in resp.json()["reason"]


def test_test_probes_the_stored_key(client, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(routes_secrets, "_probe_openai", seen.append)
    client.put("/api/secrets/OPENAI_API_KEY", json={"value": "sk-stored-0001"})
    assert client.post("/api/secrets/OPENAI_API_KEY/test").json() == {"ok": True}
    assert seen == ["sk-stored-0001"]


def test_test_prefers_an_unsaved_value_from_the_body(client, monkeypatch):
    # Lets the user check a key before committing it to disk.
    seen: list[str] = []
    monkeypatch.setattr(routes_secrets, "_probe_openai", seen.append)
    client.put("/api/secrets/OPENAI_API_KEY", json={"value": "sk-stored-0001"})
    client.post("/api/secrets/OPENAI_API_KEY/test", json={"value": " sk-typed-0002 "})
    assert seen == ["sk-typed-0002"]
    # …and testing must not save it.
    assert "sk-typed-0002" not in paths.env_file().read_text()


def test_test_routes_anthropic_to_its_own_probe(client, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(routes_secrets, "_probe_anthropic", seen.append)
    monkeypatch.setattr(
        routes_secrets, "_probe_openai", lambda key: pytest.fail("wrong provider")
    )
    resp = client.post("/api/secrets/ANTHROPIC_API_KEY/test", json={"value": "sk-ant-1"})
    assert resp.json() == {"ok": True}
    assert seen == ["sk-ant-1"]


def test_test_rejects_non_ascii_before_calling_the_provider(client, monkeypatch):
    monkeypatch.setattr(
        routes_secrets, "_probe_openai", lambda key: pytest.fail("should not be called")
    )
    resp = client.post("/api/secrets/OPENAI_API_KEY/test", json={"value": "sk-“curly”"})
    assert resp.status_code == 400


def test_auth_failure_is_ok_false_not_a_500(client, monkeypatch):
    def reject(key: str) -> None:
        raise routes_secrets._AuthRejected("OpenAI rejected this key (401 unauthorized).")

    monkeypatch.setattr(routes_secrets, "_probe_openai", reject)
    resp = client.post("/api/secrets/OPENAI_API_KEY/test", json={"value": "sk-bad"})
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": False,
        "reason": "OpenAI rejected this key (401 unauthorized).",
    }


def test_network_failure_is_ok_false_with_a_readable_reason(client, monkeypatch):
    def blow_up(key: str) -> None:
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(routes_secrets, "_probe_openai", blow_up)
    body = client.post("/api/secrets/OPENAI_API_KEY/test", json={"value": "sk-x"}).json()
    assert body["ok"] is False
    assert "Couldn't reach the provider" in body["reason"]


def test_timeout_is_ok_false_with_a_readable_reason(client, monkeypatch):
    def slow(key: str) -> None:
        raise httpx.ReadTimeout("too slow")

    monkeypatch.setattr(routes_secrets, "_probe_openai", slow)
    body = client.post("/api/secrets/OPENAI_API_KEY/test", json={"value": "sk-x"}).json()
    assert body["ok"] is False
    assert "didn't answer in time" in body["reason"]


def test_unexpected_provider_error_is_still_ok_false(client, monkeypatch):
    def boom(key: str) -> None:
        raise RuntimeError("something odd")

    monkeypatch.setattr(routes_secrets, "_probe_openai", boom)
    body = client.post("/api/secrets/OPENAI_API_KEY/test", json={"value": "sk-x"}).json()
    assert body["ok"] is False
    assert "RuntimeError" in body["reason"]


def test_test_reason_never_contains_the_key(client, monkeypatch):
    def boom(key: str) -> None:
        raise RuntimeError(f"failed with {key}")

    monkeypatch.setattr(routes_secrets, "_probe_openai", boom)
    body = client.post("/api/secrets/OPENAI_API_KEY/test", json={"value": "sk-leaky-0003"}).json()
    assert "sk-leaky-0003" not in body["reason"]


# ── provider probes (SDK mocked) ──────────────────────────────────

class _FakeModels:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc
        self.calls = 0

    def list(self, **kwargs):
        self.calls += 1
        if self.exc:
            raise self.exc
        return ["a-model"]


def _fake_sdk(monkeypatch, module_name: str, ctor_name: str, models: _FakeModels) -> dict:
    """Replace ``<module>.<ctor>`` with a stub and capture its kwargs."""
    import importlib

    module = importlib.import_module(module_name)
    captured: dict = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.models = models

    monkeypatch.setattr(module, ctor_name, _FakeClient)
    return captured


def test_probe_openai_passes_the_key_and_a_bounded_timeout(monkeypatch):
    models = _FakeModels()
    captured = _fake_sdk(monkeypatch, "openai", "OpenAI", models)
    routes_secrets._probe_openai("sk-good")
    assert captured["api_key"] == "sk-good"
    assert captured["timeout"] == routes_secrets._TEST_TIMEOUT_S
    # A failed key must not be retried three times behind a spinner.
    assert captured["max_retries"] == 0
    assert models.calls == 1


def test_probe_openai_translates_a_401(monkeypatch):
    import openai

    exc = openai.AuthenticationError(
        "bad key", response=httpx.Response(401, request=httpx.Request("GET", "http://x")), body=None
    )
    _fake_sdk(monkeypatch, "openai", "OpenAI", _FakeModels(exc))
    with pytest.raises(routes_secrets._AuthRejected, match="401"):
        routes_secrets._probe_openai("sk-bad")


def test_probe_openai_lets_transport_errors_through(monkeypatch):
    # Not an auth answer — the route maps these to a network reason instead.
    _fake_sdk(monkeypatch, "openai", "OpenAI", _FakeModels(httpx.ConnectError("down")))
    with pytest.raises(httpx.ConnectError):
        routes_secrets._probe_openai("sk-x")


def test_probe_anthropic_passes_the_key_and_a_bounded_timeout(monkeypatch):
    models = _FakeModels()
    captured = _fake_sdk(monkeypatch, "anthropic", "Anthropic", models)
    routes_secrets._probe_anthropic("sk-ant-good")
    assert captured["api_key"] == "sk-ant-good"
    assert captured["timeout"] == routes_secrets._TEST_TIMEOUT_S
    assert models.calls == 1


def test_probe_anthropic_translates_a_401(monkeypatch):
    import anthropic

    exc = anthropic.AuthenticationError(
        "bad key", response=httpx.Response(401, request=httpx.Request("GET", "http://x")), body=None
    )
    _fake_sdk(monkeypatch, "anthropic", "Anthropic", _FakeModels(exc))
    with pytest.raises(routes_secrets._AuthRejected, match="401"):
        routes_secrets._probe_anthropic("sk-ant-bad")


# ── credential_store helpers ──────────────────────────────────────

def test_mask_shows_only_the_last_four():
    assert credential_store.mask("sk-abcdefghijkl") == "…ijkl"


def test_mask_hides_everything_when_the_value_is_short():
    # Eight characters or fewer: the last four would be most of the secret.
    assert credential_store.mask("12345678") == "…"
    assert credential_store.mask("abc") == "…"


def test_get_secret_prefers_the_file_over_a_stale_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stale-from-startup")
    credential_store.save_secret("OPENAI_API_KEY", "sk-just-saved-9999")
    assert credential_store.get_secret("OPENAI_API_KEY") == "sk-just-saved-9999"


def test_get_secret_strips_quotes_written_by_hand(monkeypatch):
    # dotenv unquotes on read; read_secrets deliberately doesn't. Without the
    # strip, a hand-edited KEY="sk-…" would reach the provider wrapped in
    # quote characters and look like an invalid key.
    env = paths.env_file()
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text('OPENAI_API_KEY="sk-quoted-1234"\n')
    assert credential_store.get_secret("OPENAI_API_KEY") == "sk-quoted-1234"


def test_get_secret_returns_none_when_nothing_is_set(monkeypatch):
    assert credential_store.get_secret("OPENAI_API_KEY") is None


def test_get_secret_ignores_an_empty_file_entry(monkeypatch):
    env = paths.env_file()
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text("OPENAI_API_KEY=\n")
    assert credential_store.get_secret("OPENAI_API_KEY") is None
