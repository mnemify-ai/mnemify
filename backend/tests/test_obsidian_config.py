"""Tests for Obsidian-specific config paths.

Covers:
- get_obsidian_config() in src/config.py
- get_source_config() in src/config_file.py for obsidian
- ObsidianVaultConfig defaults
- Multi-source YAML schema round-trip for obsidian
"""

from __future__ import annotations

import pytest

from src.config_file import get_source_config, load_config_file
from src.harvester.obsidian.models import ObsidianVaultConfig


# ── ObsidianVaultConfig defaults ──────────────────────────────────────────────

def test_obsidian_vault_config_requires_vault_path():
    """vault_path is the only required field."""
    cfg = ObsidianVaultConfig(vault_path="/some/path")
    assert cfg.vault_path == "/some/path"


def test_obsidian_vault_config_defaults_to_empty_lists():
    cfg = ObsidianVaultConfig(vault_path="/some/path")
    assert cfg.watch_folders == []
    assert cfg.ignore_patterns == []


def test_obsidian_vault_config_accepts_optional_fields():
    cfg = ObsidianVaultConfig(
        vault_path="/some/path",
        watch_folders=["notes", "daily"],
        ignore_patterns=["templates/*"],
    )
    assert cfg.watch_folders == ["notes", "daily"]
    assert cfg.ignore_patterns == ["templates/*"]


# ── get_obsidian_config (src/config.py) ───────────────────────────────────────

def test_get_obsidian_config_returns_vault_path_from_dict():
    from src.config import get_obsidian_config

    result = get_obsidian_config({"vault_path": "/my/vault"})
    assert result["vault_path"] == "/my/vault"


def test_get_obsidian_config_includes_optional_fields():
    from src.config import get_obsidian_config

    source_cfg = {
        "vault_path": "/my/vault",
        "watch_folders": ["notes"],
        "ignore_patterns": ["templates/*"],
    }
    result = get_obsidian_config(source_cfg)
    assert result["watch_folders"] == ["notes"]
    assert result["ignore_patterns"] == ["templates/*"]


def test_get_obsidian_config_defaults_optional_fields_to_empty():
    from src.config import get_obsidian_config

    result = get_obsidian_config({"vault_path": "/my/vault"})
    assert result["watch_folders"] == []
    assert result["ignore_patterns"] == []


def test_get_obsidian_config_raises_when_vault_path_missing():
    from src.config import get_obsidian_config

    with pytest.raises(EnvironmentError, match="vault_path"):
        get_obsidian_config({})


def test_get_obsidian_config_raises_when_vault_path_is_empty_string():
    from src.config import get_obsidian_config

    with pytest.raises(EnvironmentError, match="vault_path"):
        get_obsidian_config({"vault_path": ""})


# ── get_source_config for obsidian (multi-source schema) ──────────────────────

def test_get_source_config_returns_obsidian_block(tmp_path):
    yaml_text = """\
sources:
  obsidian:
    vault_path: /home/user/vault
    watch_folders:
      - notes
      - daily
    ignore_patterns:
      - templates/*
"""
    cfg_file = tmp_path / "mnemify.yaml"
    cfg_file.write_text(yaml_text, encoding="utf-8")

    file_cfg = load_config_file(explicit_path=cfg_file)
    obsidian_cfg = get_source_config(file_cfg, "obsidian")

    assert obsidian_cfg["vault_path"] == "/home/user/vault"
    assert obsidian_cfg["watch_folders"] == ["notes", "daily"]
    assert obsidian_cfg["ignore_patterns"] == ["templates/*"]


def test_get_source_config_obsidian_returns_empty_dict_when_not_configured(tmp_path):
    yaml_text = "sources:\n  notion:\n    token_env: NOTION_TOKEN\n"
    cfg_file = tmp_path / "mnemify.yaml"
    cfg_file.write_text(yaml_text, encoding="utf-8")

    file_cfg = load_config_file(explicit_path=cfg_file)
    obsidian_cfg = get_source_config(file_cfg, "obsidian")

    assert obsidian_cfg == {}


def test_get_source_config_obsidian_returns_empty_dict_for_legacy_schema(tmp_path):
    """Legacy flat schema only contained Notion; obsidian should return empty."""
    yaml_text = "source: notion\nconcurrency: 5\n"
    cfg_file = tmp_path / "mnemify.yaml"
    cfg_file.write_text(yaml_text, encoding="utf-8")

    file_cfg = load_config_file(explicit_path=cfg_file)
    obsidian_cfg = get_source_config(file_cfg, "obsidian")

    assert obsidian_cfg == {}


def test_get_source_config_multi_source_both_sources(tmp_path):
    """Multi-source config should independently return both notion and obsidian."""
    yaml_text = """\
sources:
  notion:
    token_env: NOTION_TOKEN
    concurrency: 5
  obsidian:
    vault_path: /home/user/vault
"""
    cfg_file = tmp_path / "mnemify.yaml"
    cfg_file.write_text(yaml_text, encoding="utf-8")

    file_cfg = load_config_file(explicit_path=cfg_file)

    notion_cfg = get_source_config(file_cfg, "notion")
    obsidian_cfg = get_source_config(file_cfg, "obsidian")

    assert notion_cfg["token_env"] == "NOTION_TOKEN"
    assert obsidian_cfg["vault_path"] == "/home/user/vault"


