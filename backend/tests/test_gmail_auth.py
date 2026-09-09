"""Tests for :mod:`src.harvester.gmail.auth`.

The Gmail auth module is now a thin wrapper that bakes in
``GMAIL_SCOPES`` and the env-var name, then delegates to the shared
:mod:`src.harvester._google.oauth` helpers. Tests focus on:

- The wrapper passes the right scope and env-var name through.
- Missing-token / missing-bundle paths surface clear error messages.
- The interactive ``run_consent_flow`` is patched out (browser-popping
  isn't testable in CI).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.harvester.gmail import auth as gmail_auth


# ── Constants are stable ────────────────────────────────────────


def test_gmail_scope_is_readonly():
    """The minimum scope choice is part of the consent-screen contract."""
    assert gmail_auth.GMAIL_SCOPES == [
        "https://www.googleapis.com/auth/gmail.readonly"
    ]


def test_gmail_credentials_env_name():
    assert gmail_auth.GMAIL_CREDENTIALS_ENV == "GMAIL_CREDENTIALS_PATH"


# ── load_credentials — delegates to shared module ───────────────


def test_load_credentials_delegates_with_gmail_scopes_and_env(monkeypatch, tmp_path: Path):
    """The wrapper must forward scopes + env-var name verbatim."""
    captured: dict = {}

    def fake_load(*, scopes, token_path, client_secrets_path, client_secrets_env):
        captured["scopes"] = scopes
        captured["token_path"] = token_path
        captured["client_secrets_path"] = client_secrets_path
        captured["client_secrets_env"] = client_secrets_env
        return "fake-creds"

    monkeypatch.setattr("src.harvester._google.oauth.load_credentials", fake_load)

    out = gmail_auth.load_credentials(
        str(tmp_path / "token.json"),
        client_secrets_path="/tmp/client.json",
    )

    assert out == "fake-creds"
    assert captured["scopes"] == gmail_auth.GMAIL_SCOPES
    assert captured["token_path"] == str(tmp_path / "token.json")
    assert captured["client_secrets_path"] == "/tmp/client.json"
    assert captured["client_secrets_env"] == "GMAIL_CREDENTIALS_PATH"


# ── run_consent_flow — delegates to shared module ───────────────


def test_run_consent_flow_delegates_with_gmail_scopes_and_env(monkeypatch, tmp_path: Path):
    captured: dict = {}

    def fake_consent(*, scopes, token_path, client_secrets_path, client_secrets_env):
        captured["scopes"] = scopes
        captured["token_path"] = token_path
        captured["client_secrets_path"] = client_secrets_path
        captured["client_secrets_env"] = client_secrets_env

    monkeypatch.setattr("src.harvester._google.oauth.run_consent_flow", fake_consent)

    gmail_auth.run_consent_flow(str(tmp_path / "token.json"))

    assert captured["scopes"] == gmail_auth.GMAIL_SCOPES
    assert captured["client_secrets_env"] == "GMAIL_CREDENTIALS_PATH"
    assert captured["client_secrets_path"] is None  # not provided → defaults to None


# ── Failure surfacing ───────────────────────────────────────────


def test_missing_token_surfaces_environment_error(monkeypatch, tmp_path: Path):
    """When the token cache is missing, the wrapper surfaces a usable error."""
    # Provide a bundle so the OAuth-client side resolves cleanly; only
    # the token cache is missing — that's what we want to test.
    from src.harvester._google import oauth as google_oauth

    bundled = tmp_path / "bundled.json"
    bundled.write_text("{}")
    monkeypatch.setattr(google_oauth, "DEFAULT_BUNDLED_CLIENT", bundled)
    monkeypatch.delenv("GMAIL_CREDENTIALS_PATH", raising=False)

    with pytest.raises(EnvironmentError) as excinfo:
        gmail_auth.load_credentials(str(tmp_path / "no-token.json"))
    assert "mnemify login" in str(excinfo.value)
