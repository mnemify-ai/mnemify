"""Tests for ``src.paths`` — the single resolver for on-disk state.

Two things are under test here:

1. The precedence rules (``MNEMIFY_HOME`` → legacy ``backend/`` layout →
   platform app-data dir) and the per-file ``MNEMIFY_ENV_FILE`` /
   ``MNEMIFY_YAML_FILE`` overrides.
2. The regression this phase exists to kill: the UI wrote ``.env`` /
   ``mnemify.yaml`` through ``paths`` while the loaders read them from the
   process cwd, so a token saved by the wizard was invisible to the
   harvester whenever the server had been started from another directory.

The autouse ``_isolated_mnemify_home`` fixture in ``conftest.py`` sets
``MNEMIFY_HOME`` for every test, so any test of the *fallback* branches has
to delete it first — otherwise ``layout()`` is ``"env"`` unconditionally and
the assertion passes for the wrong reason.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src import paths

# ── MNEMIFY_HOME (precedence rule 1) ─────────────────────────────────────────

def test_env_home_wins(tmp_path, monkeypatch):
    target = tmp_path / "somewhere-else"
    monkeypatch.setenv("MNEMIFY_HOME", str(target))
    assert paths.home() == target.resolve()
    assert paths.layout() == "env"
    assert paths.data_dir() == target.resolve() / ".mnemify"
    assert paths.yaml_file() == target.resolve() / "mnemify.yaml"
    assert paths.env_file() == target.resolve() / ".env"


def test_env_home_expands_tilde(monkeypatch):
    monkeypatch.setenv("MNEMIFY_HOME", "~/mnemify-home-test")
    assert paths.home() == (Path.home() / "mnemify-home-test").resolve()


def test_ensure_home_creates_the_directory(tmp_path, monkeypatch):
    target = tmp_path / "fresh"
    monkeypatch.setenv("MNEMIFY_HOME", str(target))
    assert not target.exists()
    assert paths.ensure_home() == target.resolve()
    assert target.is_dir()


# ── Legacy backend/ layout (precedence rule 2) ───────────────────────────────

@pytest.mark.parametrize("marker", [".mnemify", "mnemify.yaml", ".env"])
def test_legacy_layout_detected_from_any_marker(tmp_path, monkeypatch, marker):
    fake_backend = tmp_path / "backend"
    fake_backend.mkdir()
    if marker == ".mnemify":
        (fake_backend / marker).mkdir()
    else:
        (fake_backend / marker).write_text("", encoding="utf-8")

    monkeypatch.delenv("MNEMIFY_HOME", raising=False)
    monkeypatch.setattr(paths, "_BACKEND_DIR", fake_backend)

    assert paths.layout() == "legacy"
    assert paths.home() == fake_backend
    assert paths.data_dir() == fake_backend / ".mnemify"


def test_env_home_beats_legacy_layout(tmp_path, monkeypatch):
    fake_backend = tmp_path / "backend"
    (fake_backend / ".mnemify").mkdir(parents=True)
    override = tmp_path / "override"

    monkeypatch.setattr(paths, "_BACKEND_DIR", fake_backend)
    monkeypatch.setenv("MNEMIFY_HOME", str(override))

    assert paths.layout() == "env"
    assert paths.home() == override.resolve()


def test_no_markers_falls_through_to_platform(tmp_path, monkeypatch):
    empty_backend = tmp_path / "backend"
    empty_backend.mkdir()

    monkeypatch.delenv("MNEMIFY_HOME", raising=False)
    monkeypatch.setattr(paths, "_BACKEND_DIR", empty_backend)

    assert paths.layout() == "platform"
    assert paths.home() == paths.platform_default()


# ── Platform default (precedence rule 3) ─────────────────────────────────────

def test_platform_default_macos(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    assert paths.platform_default() == (
        Path.home() / "Library" / "Application Support" / "Mnemify"
    )


def test_platform_default_windows_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    assert paths.platform_default() == tmp_path / "AppData" / "Local" / "Mnemify"


def test_platform_default_windows_without_localappdata(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert paths.platform_default() == (
        Path.home() / "AppData" / "Local" / "Mnemify"
    )


def test_platform_default_linux_honours_xdg(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.platform_default() == tmp_path / "xdg" / "mnemify"


def test_platform_default_linux_without_xdg(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.platform_default() == Path.home() / ".local" / "share" / "mnemify"


# ── Per-file overrides ───────────────────────────────────────────────────────

def test_env_and_yaml_file_overrides_beat_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("MNEMIFY_HOME", str(home))
    monkeypatch.setenv("MNEMIFY_ENV_FILE", str(tmp_path / "custom" / "secrets.env"))
    monkeypatch.setenv("MNEMIFY_YAML_FILE", str(tmp_path / "custom" / "conf.yaml"))

    assert paths.env_file() == (tmp_path / "custom" / "secrets.env").resolve()
    assert paths.yaml_file() == (tmp_path / "custom" / "conf.yaml").resolve()
    # The overrides are per-file: the data dir still follows home().
    assert paths.data_dir() == home.resolve() / ".mnemify"


# ── resolve_under_data_dir ───────────────────────────────────────────────────

def test_resolve_under_data_dir_anchors_relative_to_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMIFY_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path.parent)  # cwd must not matter

    # This is the literal `yaml_writer` stamps into a fresh mnemify.yaml.
    assert paths.resolve_under_data_dir(".mnemify/raw") == paths.data_dir() / "raw"
    assert paths.resolve_under_data_dir("elsewhere") == tmp_path.resolve() / "elsewhere"


def test_resolve_under_data_dir_passes_absolute_through(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMIFY_HOME", str(tmp_path))
    absolute = tmp_path.parent / "external-raw"
    assert paths.resolve_under_data_dir(absolute) == absolute
    assert paths.resolve_under_data_dir(str(absolute)) == absolute


# ── describe() ───────────────────────────────────────────────────────────────

def test_describe_reports_env_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMIFY_HOME", str(tmp_path))
    info = paths.describe()
    assert info["layout"] == "env"
    assert info["home"] == str(tmp_path.resolve())
    assert info["data_dir"] == str(tmp_path.resolve() / ".mnemify")
    assert set(info) == {"layout", "home", "data_dir", "yaml_file", "env_file"}


def test_describe_reports_legacy_and_platform_layouts(tmp_path, monkeypatch):
    fake_backend = tmp_path / "backend"
    (fake_backend / ".mnemify").mkdir(parents=True)
    monkeypatch.delenv("MNEMIFY_HOME", raising=False)
    monkeypatch.setattr(paths, "_BACKEND_DIR", fake_backend)
    assert paths.describe()["layout"] == "legacy"

    (fake_backend / ".mnemify").rmdir()
    assert paths.describe()["layout"] == "platform"


# ── Regression: writes and reads resolve to the same files ───────────────────

def test_ui_writes_are_visible_to_the_loaders_from_any_cwd(tmp_path, monkeypatch):
    """A token saved by the wizard must be the token the harvester loads.

    Before this phase ``credential_store``/``yaml_writer`` wrote through
    ``MNEMIFY_HOME`` while ``config.load_config`` / ``config_file`` read
    ``./.env`` and ``./mnemify.yaml`` — so from any cwd but the home dir the
    reads silently found nothing.
    """
    from src import config, config_file
    from src.api import credential_store, yaml_writer

    monkeypatch.setenv("MNEMIFY_HOME", str(tmp_path))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    # load_dotenv() will not override an already-set value, so a leaked
    # NOTION_TOKEN would make the assertion below pass vacuously.
    monkeypatch.delenv("NOTION_TOKEN", raising=False)

    credential_store.save_secret("NOTION_TOKEN", "x")
    yaml_writer.upsert_source("notion", {"enabled": True})

    # Written where paths says, not into the cwd.
    assert (tmp_path / ".env").is_file()
    assert (tmp_path / "mnemify.yaml").is_file()
    assert not (elsewhere / ".env").exists()
    assert not (elsewhere / "mnemify.yaml").exists()

    config.load_config()
    assert os.environ["NOTION_TOKEN"] == "x"
    assert config_file.load_config_file()["sources"]["notion"]["enabled"] is True
