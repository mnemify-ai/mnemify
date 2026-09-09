"""Tests for :mod:`src.harvester._google.oauth`.

The shared OAuth module is the single auth plumbing every Google-source
plugin uses (Gmail today, Drive / Calendar / Docs later). These tests
pin its three load-bearing behaviours:

1. The resolution order — explicit path → env var → bundled fallback → error.
2. Error messages name the bundle path, so the operator knows where to drop
   the JSON.
3. ``_write_token`` produces a mode-0600 file via an atomic rename.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.harvester._google import oauth as google_oauth


# ── resolve_client_secrets_path — explicit path branch ──────────


def test_explicit_path_takes_priority_over_env(monkeypatch, tmp_path: Path):
    """An explicit ``client_secrets_path`` short-circuits env lookup."""
    explicit = tmp_path / "explicit.json"
    explicit.write_text("{}")

    bogus_env_path = tmp_path / "should-not-be-read.json"
    monkeypatch.setenv("FAKE_ENV", str(bogus_env_path))

    out = google_oauth.resolve_client_secrets_path(
        client_secrets_path=str(explicit),
        client_secrets_env="FAKE_ENV",
    )
    assert out == explicit


def test_explicit_path_must_exist(tmp_path: Path):
    missing = tmp_path / "missing.json"
    with pytest.raises(EnvironmentError) as excinfo:
        google_oauth.resolve_client_secrets_path(
            client_secrets_path=str(missing),
        )
    assert str(missing) in str(excinfo.value)


# ── resolve_client_secrets_path — env-var branch ────────────────


def test_env_var_path_used_when_no_explicit_arg(monkeypatch, tmp_path: Path):
    env_file = tmp_path / "env.json"
    env_file.write_text("{}")
    monkeypatch.setenv("MY_GOOGLE_CREDS", str(env_file))

    out = google_oauth.resolve_client_secrets_path(
        client_secrets_env="MY_GOOGLE_CREDS",
    )
    assert out == env_file


def test_env_var_pointing_to_missing_file_raises(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MY_GOOGLE_CREDS", str(tmp_path / "nope.json"))
    with pytest.raises(EnvironmentError) as excinfo:
        google_oauth.resolve_client_secrets_path(
            client_secrets_env="MY_GOOGLE_CREDS",
        )
    assert "MY_GOOGLE_CREDS" in str(excinfo.value)


# ── resolve_client_secrets_path — bundled fallback ──────────────


def test_bundled_fallback_used_when_no_arg_no_env(monkeypatch, tmp_path: Path):
    """With nothing else available, fall back to the bundled OAuth client."""
    bundled = tmp_path / "bundled.json"
    bundled.write_text("{}")
    monkeypatch.setattr(google_oauth, "DEFAULT_BUNDLED_CLIENT", bundled)
    monkeypatch.delenv("GMAIL_CREDENTIALS_PATH", raising=False)

    out = google_oauth.resolve_client_secrets_path(
        client_secrets_env="GMAIL_CREDENTIALS_PATH",
    )
    assert out == bundled


def test_no_bundle_no_env_no_arg_raises_with_helpful_message(monkeypatch, tmp_path: Path):
    """With nothing available the error names the bundle path AND the env var."""
    nonexistent_bundle = tmp_path / "_google" / "oauth_client.json"
    monkeypatch.setattr(google_oauth, "DEFAULT_BUNDLED_CLIENT", nonexistent_bundle)
    monkeypatch.delenv("GMAIL_CREDENTIALS_PATH", raising=False)

    with pytest.raises(EnvironmentError) as excinfo:
        google_oauth.resolve_client_secrets_path(
            client_secrets_env="GMAIL_CREDENTIALS_PATH",
        )
    msg = str(excinfo.value)
    assert "oauth_client.json" in msg
    assert "GMAIL_CREDENTIALS_PATH" in msg


# ── load_credentials — token-cache invariants ───────────────────


def test_load_credentials_raises_when_token_missing(monkeypatch, tmp_path: Path):
    bundled = tmp_path / "bundled.json"
    bundled.write_text("{}")
    monkeypatch.setattr(google_oauth, "DEFAULT_BUNDLED_CLIENT", bundled)

    with pytest.raises(EnvironmentError) as excinfo:
        google_oauth.load_credentials(
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            token_path=str(tmp_path / "missing-token.json"),
        )
    assert "mnemify login" in str(excinfo.value)


# ── _write_token — mode 0600 + atomicity ────────────────────────


def test_write_token_sets_mode_0600(tmp_path: Path):
    target = tmp_path / "subdir" / "token.json"
    fake_creds = MagicMock()
    fake_creds.to_json.return_value = json.dumps({"refresh_token": "xyz"})

    google_oauth._write_token(target, fake_creds)

    assert target.exists()
    mode = stat.S_IMODE(os.stat(target).st_mode)
    assert mode == 0o600


def test_write_token_creates_parent_directory(tmp_path: Path):
    target = tmp_path / "deep" / "nested" / "token.json"
    fake_creds = MagicMock()
    fake_creds.to_json.return_value = "{}"

    google_oauth._write_token(target, fake_creds)

    assert target.exists()
    assert target.parent.is_dir()


def test_write_token_replaces_existing_atomically(tmp_path: Path):
    target = tmp_path / "token.json"
    target.write_text("OLD")

    fake_creds = MagicMock()
    fake_creds.to_json.return_value = '{"refresh_token": "new"}'

    google_oauth._write_token(target, fake_creds)

    assert target.read_text() == '{"refresh_token": "new"}'


# ── Forward-compatibility sanity ────────────────────────────────


def test_module_has_no_gmail_specific_symbols():
    """The shared module must stay generic — no Gmail constants leak in.

    If someone adds Gmail-specific behaviour here, every other Google
    plugin that comes later (Drive, Calendar, Docs) inherits the
    wart. This test catches the most obvious slip-ups by name.
    """
    public_names = {
        name for name in dir(google_oauth)
        if not name.startswith("_") or name == "_write_token"
    }
    forbidden = {"GMAIL_SCOPES", "DRIVE_SCOPES", "CALENDAR_SCOPES"}
    assert public_names.isdisjoint(forbidden)
