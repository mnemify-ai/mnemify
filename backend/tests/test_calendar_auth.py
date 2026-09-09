"""Tests for :mod:`src.harvester.calendar.auth`.

The Calendar auth module is a thin wrapper that bakes in
``CALENDAR_SCOPES`` and the env-var name, then delegates to the
shared :mod:`src.harvester._google.oauth` helpers. These tests verify
the wrapper passes the right scope and env-var name through.
"""

from __future__ import annotations

from pathlib import Path

from src.harvester.calendar import auth as calendar_auth


def test_calendar_scope_is_readonly():
    assert calendar_auth.CALENDAR_SCOPES == [
        "https://www.googleapis.com/auth/calendar.readonly"
    ]


def test_calendar_credentials_env_name():
    assert calendar_auth.CALENDAR_CREDENTIALS_ENV == "CALENDAR_CREDENTIALS_PATH"


def test_load_credentials_delegates_with_calendar_scopes_and_env(monkeypatch, tmp_path: Path):
    captured: dict = {}

    def fake_load(*, scopes, token_path, client_secrets_path, client_secrets_env):
        captured["scopes"] = scopes
        captured["token_path"] = token_path
        captured["client_secrets_path"] = client_secrets_path
        captured["client_secrets_env"] = client_secrets_env
        return "fake-creds"

    monkeypatch.setattr("src.harvester._google.oauth.load_credentials", fake_load)

    out = calendar_auth.load_credentials(
        str(tmp_path / "token.json"),
        client_secrets_path="/tmp/client.json",
    )

    assert out == "fake-creds"
    assert captured["scopes"] == calendar_auth.CALENDAR_SCOPES
    assert captured["token_path"] == str(tmp_path / "token.json")
    assert captured["client_secrets_path"] == "/tmp/client.json"
    assert captured["client_secrets_env"] == "CALENDAR_CREDENTIALS_PATH"


def test_run_consent_flow_delegates_with_calendar_scopes_and_env(monkeypatch, tmp_path: Path):
    captured: dict = {}

    def fake_consent(*, scopes, token_path, client_secrets_path, client_secrets_env):
        captured["scopes"] = scopes
        captured["token_path"] = token_path
        captured["client_secrets_path"] = client_secrets_path
        captured["client_secrets_env"] = client_secrets_env

    monkeypatch.setattr("src.harvester._google.oauth.run_consent_flow", fake_consent)

    calendar_auth.run_consent_flow(str(tmp_path / "token.json"))

    assert captured["scopes"] == calendar_auth.CALENDAR_SCOPES
    assert captured["client_secrets_env"] == "CALENDAR_CREDENTIALS_PATH"
    assert captured["client_secrets_path"] is None
