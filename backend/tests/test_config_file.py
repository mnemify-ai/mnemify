"""Unit tests for src/config_file.py."""

from __future__ import annotations


import pytest

from src.config_file import get_source_config, load_config_file


# ── Loading ────────────────────────────────────────────────────────


def test_load_explicit_path_returns_parsed_yaml(tmp_path):
    cfg = tmp_path / "my.yaml"
    cfg.write_text("source: notion\nconcurrency: 3\n", encoding="utf-8")

    result = load_config_file(explicit_path=cfg)

    assert result["source"] == "notion"
    assert result["concurrency"] == 3


def test_load_returns_dict_with_nested_section(tmp_path):
    cfg = tmp_path / "mnemify.yaml"
    cfg.write_text(
        "write_back:\n  enabled: true\n  property: \"Harvested At\"\n",
        encoding="utf-8",
    )

    result = load_config_file(explicit_path=cfg)

    assert result["write_back"]["enabled"] is True
    assert result["write_back"]["property"] == "Harvested At"


def test_load_empty_yaml_returns_empty_dict(tmp_path):
    cfg = tmp_path / "empty.yaml"
    cfg.write_text("", encoding="utf-8")

    result = load_config_file(explicit_path=cfg)

    assert result == {}


def test_load_no_file_found_returns_empty_dict(tmp_path, monkeypatch):
    """When no file exists in search paths, return empty dict."""
    # Override search path so we never accidentally find ~/.mnemify/mnemify.yaml
    import src.config_file as cf_module

    monkeypatch.setattr(
        cf_module,
        "_DEFAULT_SEARCH_PATHS",
        [tmp_path / "nonexistent.yaml"],
    )

    result = load_config_file()

    assert result == {}


# ── Explicit path errors ───────────────────────────────────────────


def test_load_explicit_path_missing_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config_file(explicit_path=tmp_path / "does_not_exist.yaml")


def test_load_bad_yaml_raises_value_error(tmp_path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("key: [unclosed bracket", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid YAML"):
        load_config_file(explicit_path=cfg)


def test_load_non_mapping_yaml_raises_value_error(tmp_path):
    cfg = tmp_path / "list.yaml"
    cfg.write_text("- item1\n- item2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a YAML mapping"):
        load_config_file(explicit_path=cfg)


# ── Search order ───────────────────────────────────────────────────


def test_search_order_explicit_wins_over_cwd(tmp_path, monkeypatch):
    """Explicit path must win over local mnemify.yaml."""
    cwd_cfg = tmp_path / "mnemify.yaml"
    cwd_cfg.write_text("source: cwd\n", encoding="utf-8")

    explicit_cfg = tmp_path / "explicit.yaml"
    explicit_cfg.write_text("source: explicit\n", encoding="utf-8")

    import src.config_file as cf_module

    monkeypatch.setattr(
        cf_module,
        "_DEFAULT_SEARCH_PATHS",
        [cwd_cfg],
    )

    result = load_config_file(explicit_path=explicit_cfg)

    assert result["source"] == "explicit"


def test_search_order_first_match_wins(tmp_path, monkeypatch):
    """First file in the search path list is used."""
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text("source: first\n", encoding="utf-8")
    second.write_text("source: second\n", encoding="utf-8")

    import src.config_file as cf_module

    monkeypatch.setattr(cf_module, "_DEFAULT_SEARCH_PATHS", [first, second])

    result = load_config_file()

    assert result["source"] == "first"


def test_search_order_skips_missing_files(tmp_path, monkeypatch):
    """If the first candidate doesn't exist, fall through to the next."""
    missing = tmp_path / "missing.yaml"
    present = tmp_path / "present.yaml"
    present.write_text("source: present\n", encoding="utf-8")

    import src.config_file as cf_module

    monkeypatch.setattr(cf_module, "_DEFAULT_SEARCH_PATHS", [missing, present])

    result = load_config_file()

    assert result["source"] == "present"


# ── Full schema round-trip ─────────────────────────────────────────


def test_full_schema_parses_correctly(tmp_path):
    yaml_text = """\
source: notion
concurrency: 5
raw_root: .mnemify/raw
converter_version: "0.1.0"
write_back:
  enabled: false
  property: "Harvested At"
"""
    cfg = tmp_path / "mnemify.yaml"
    cfg.write_text(yaml_text, encoding="utf-8")

    result = load_config_file(explicit_path=cfg)

    assert result["source"] == "notion"
    assert result["concurrency"] == 5
    assert result["converter_version"] == "0.1.0"
    assert result["write_back"]["enabled"] is False
    assert result["write_back"]["property"] == "Harvested At"


# ── Atlassian source blocks (ATL-05) ───────────────────────────────


def test_atlassian_source_blocks_parse(tmp_path):
    """The docstring examples for sources.confluence and sources.jira
    must round-trip through load_config_file + get_source_config into
    plain dicts whose keys match the respective ``*Config`` dataclass
    fields documented in ``src/harvester/{confluence,jira}/models.py``.
    """
    yaml_text = """\
sources:
  confluence:
    enabled: true
    base_url: "https://your-org.atlassian.net/wiki"
    email_env: "CONFLUENCE_EMAIL"
    token_env: "CONFLUENCE_API_TOKEN"
    space_keys: ["ENG", "PROD"]
    concurrency: 3

  jira:
    enabled: true
    base_url: "https://your-org.atlassian.net"
    email_env: "JIRA_EMAIL"
    token_env: "JIRA_API_TOKEN"
    project_keys: ["CONN", "PLAT"]
    story_points_field: null
    concurrency: 3
"""
    cfg = tmp_path / "mnemify.yaml"
    cfg.write_text(yaml_text, encoding="utf-8")

    result = load_config_file(explicit_path=cfg)

    # Both source blocks must be reachable via the multi-source helper.
    confluence_cfg = get_source_config(result, "confluence")
    jira_cfg = get_source_config(result, "jira")

    # Confluence — keys align with ConfluenceConfig dataclass fields.
    assert confluence_cfg["enabled"] is True
    assert confluence_cfg["base_url"] == "https://your-org.atlassian.net/wiki"
    assert confluence_cfg["email_env"] == "CONFLUENCE_EMAIL"
    assert confluence_cfg["token_env"] == "CONFLUENCE_API_TOKEN"
    assert confluence_cfg["space_keys"] == ["ENG", "PROD"]
    assert confluence_cfg["concurrency"] == 3

    # Jira — keys align with JiraConfig dataclass fields.
    assert jira_cfg["enabled"] is True
    assert jira_cfg["base_url"] == "https://your-org.atlassian.net"
    assert jira_cfg["email_env"] == "JIRA_EMAIL"
    assert jira_cfg["token_env"] == "JIRA_API_TOKEN"
    assert jira_cfg["project_keys"] == ["CONN", "PLAT"]
    assert jira_cfg["story_points_field"] is None  # null → auto-discover
    assert jira_cfg["concurrency"] == 3


def test_missing_sources_block_returns_empty_dict():
    """When a loaded config has no ``sources`` key (and is not the
    legacy flat Notion schema), :func:`get_source_config` must return
    an empty dict for any source_type — callers rely on this to fall
    back to CLI-flag-only configuration without raising.
    """
    # No ``sources`` key, not the legacy flat Notion schema.
    empty_cfg: dict = {}

    assert get_source_config(empty_cfg, "confluence") == {}
    assert get_source_config(empty_cfg, "jira") == {}
    assert get_source_config(empty_cfg, "obsidian") == {}

    # An unrelated top-level key must not accidentally match.
    unrelated_cfg = {"raw_root": ".mnemify/raw"}
    assert get_source_config(unrelated_cfg, "confluence") == {}
    assert get_source_config(unrelated_cfg, "jira") == {}
