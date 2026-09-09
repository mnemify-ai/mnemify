"""Tests for the plugin registry (src/harvester/registry.py).

Covers: register_plugin, create_plugin, registered_source_types,
unknown-source ValueError, lazy import, factory overwrite.
"""

from __future__ import annotations

import pytest

from src.harvester import SourcePlugin
from src.harvester.registry import (
    create_plugin,
    register_plugin,
    registered_source_types,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

class _FakePlugin(SourcePlugin):
    """Minimal concrete plugin for registry testing."""

    async def test_connection(self):
        ...

    async def list_documents(self, since=None):
        return []

    async def fetch_document(self, doc_ref):
        ...

    async def fetch_attachment(self, att_ref):
        return b""


def _fake_factory(config: dict) -> tuple[_FakePlugin, None]:
    return _FakePlugin(), None


# ── 1. register_plugin / registered_source_types ──────────────────────────────

def test_register_plugin_appears_in_registered_types():
    register_plugin("_test_source_a", _fake_factory)
    assert "_test_source_a" in registered_source_types()


def test_registered_source_types_is_sorted():
    register_plugin("_zzz_source", _fake_factory)
    register_plugin("_aaa_source", _fake_factory)
    types = registered_source_types()
    assert types == sorted(types)


def test_register_plugin_overwrites_previous_registration():
    """Last write wins — silent overwrite."""
    counter = {"n": 0}

    def factory_v1(cfg):
        counter["n"] = 1
        return _FakePlugin(), None

    def factory_v2(cfg):
        counter["n"] = 2
        return _FakePlugin(), None

    register_plugin("_overwrite_source", factory_v1)
    register_plugin("_overwrite_source", factory_v2)
    create_plugin("_overwrite_source", {})
    assert counter["n"] == 2, "Expected factory_v2 to be called after overwrite"


# ── 2. create_plugin ──────────────────────────────────────────────────────────

def test_create_plugin_returns_plugin_and_none_for_stateless_source():
    register_plugin("_stateless_source", _fake_factory)
    plugin, client = create_plugin("_stateless_source", {})
    assert isinstance(plugin, SourcePlugin)
    assert client is None


def test_create_plugin_passes_config_to_factory():
    received = {}

    def capturing_factory(config: dict):
        received.update(config)
        return _FakePlugin(), None

    register_plugin("_config_source", capturing_factory)
    create_plugin("_config_source", {"key": "value", "num": 42})
    assert received == {"key": "value", "num": 42}


def test_create_plugin_raises_for_unknown_source_type():
    with pytest.raises(ValueError, match="Unknown source type"):
        create_plugin("does_not_exist_xyz", {})


def test_create_plugin_error_message_lists_available_types():
    register_plugin("_known_source", _fake_factory)
    try:
        create_plugin("totally_unknown_source", {})
    except ValueError as exc:
        assert "_known_source" in str(exc) or "Available:" in str(exc)


# ── 3. Built-in sources are registered after lazy import ─────────────────────

def test_notion_is_registered_after_lazy_import():
    # create_plugin triggers _ensure_plugins_registered
    types = registered_source_types()
    assert "notion" in types


def test_obsidian_is_registered_after_lazy_import():
    types = registered_source_types()
    assert "obsidian" in types


def test_confluence_is_registered():
    """ATL-04: confluence plugin auto-registers via _ensure_plugins_registered.

    The test must *not* explicitly import ``src.harvester.confluence`` —
    the point of the registry wiring is that merely calling
    ``registered_source_types()`` is sufficient to trigger registration.
    """
    from src.harvester.registry import _ensure_plugins_registered

    _ensure_plugins_registered()
    assert "confluence" in registered_source_types()


def test_jira_is_registered():
    """ATL-04: jira plugin auto-registers via _ensure_plugins_registered.

    As with confluence, this test must not import ``src.harvester.jira``
    directly — the registry wiring is what's under test.
    """
    from src.harvester.registry import _ensure_plugins_registered

    _ensure_plugins_registered()
    assert "jira" in registered_source_types()


# ── 4. create_plugin instantiates the obsidian plugin correctly ───────────────

def test_create_obsidian_plugin_returns_obsidian_plugin(tmp_path):
    """Factory round-trip with a real ObsidianVaultConfig."""
    from src.harvester.obsidian.plugin import ObsidianHarvesterPlugin

    # Minimal valid config
    cfg = {"vault_path": str(tmp_path)}
    plugin, client = create_plugin("obsidian", cfg)
    assert isinstance(plugin, ObsidianHarvesterPlugin)
    assert client is None


def test_create_obsidian_plugin_accepts_optional_fields(tmp_path):
    cfg = {
        "vault_path": str(tmp_path),
        "watch_folders": ["notes"],
        "ignore_patterns": ["templates/*"],
    }
    from src.harvester.obsidian.plugin import ObsidianHarvesterPlugin

    plugin, _ = create_plugin("obsidian", cfg)
    assert isinstance(plugin, ObsidianHarvesterPlugin)
    assert plugin.scanner.watch_folders == ["notes"]


def test_create_plugin_error_on_missing_obsidian_vault_path():
    """Obsidian factory requires vault_path; missing key raises KeyError."""
    with pytest.raises(KeyError):
        create_plugin("obsidian", {})


# ── 5. ATL-14 — Confluence factory env-var resolution ────────────


def test_create_confluence_plugin_success_with_env_vars(monkeypatch):
    """Happy path: both env vars set → factory returns (plugin, None)."""
    from src.harvester.confluence import ConfluenceHarvesterPlugin

    monkeypatch.setenv("CONFLUENCE_EMAIL", "bot@example.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "tok-xyz")
    cfg = {
        "base_url": "https://example.atlassian.net/wiki",
        "space_keys": ["ENG"],
    }
    plugin, closeable = create_plugin("confluence", cfg)
    assert isinstance(plugin, ConfluenceHarvesterPlugin)
    # Per plan §2.2: factory returns (plugin, None) — teardown is plugin.aclose().
    assert closeable is None


def test_create_confluence_plugin_success_with_inline_creds(monkeypatch):
    """Inline ``email``/``token`` in the config satisfy the factory even when env vars are unset."""
    from src.harvester.confluence import ConfluenceHarvesterPlugin

    monkeypatch.delenv("CONFLUENCE_EMAIL", raising=False)
    monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
    cfg = {
        "base_url": "https://example.atlassian.net/wiki",
        "email": "bot@example.com",
        "token": "tok-xyz",
        "space_keys": ["ENG"],
    }
    plugin, _ = create_plugin("confluence", cfg)
    assert isinstance(plugin, ConfluenceHarvesterPlugin)


def test_create_confluence_plugin_raises_when_email_missing(monkeypatch):
    """Missing email env var → EnvironmentError naming the offender."""
    monkeypatch.delenv("CONFLUENCE_EMAIL", raising=False)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "tok-xyz")
    cfg = {"base_url": "https://example.atlassian.net/wiki"}
    with pytest.raises(EnvironmentError) as excinfo:
        create_plugin("confluence", cfg)
    # Remediation message names the env var so the user knows what to set.
    assert "CONFLUENCE_EMAIL" in str(excinfo.value)


def test_create_confluence_plugin_raises_when_token_missing(monkeypatch):
    """Missing token env var → EnvironmentError naming the offender."""
    monkeypatch.setenv("CONFLUENCE_EMAIL", "bot@example.com")
    monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
    cfg = {"base_url": "https://example.atlassian.net/wiki"}
    with pytest.raises(EnvironmentError) as excinfo:
        create_plugin("confluence", cfg)
    assert "CONFLUENCE_API_TOKEN" in str(excinfo.value)


def test_create_confluence_plugin_honours_custom_email_env(monkeypatch):
    """When ``email_env`` is overridden, the error message names the custom var."""
    monkeypatch.delenv("CONFLUENCE_EMAIL", raising=False)
    monkeypatch.delenv("ATLASSIAN_EMAIL", raising=False)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "tok-xyz")
    cfg = {
        "base_url": "https://example.atlassian.net/wiki",
        "email_env": "ATLASSIAN_EMAIL",
    }
    with pytest.raises(EnvironmentError) as excinfo:
        create_plugin("confluence", cfg)
    assert "ATLASSIAN_EMAIL" in str(excinfo.value)
    # And the default env var name must NOT appear (we correctly honoured the override).
    assert "CONFLUENCE_EMAIL" not in str(excinfo.value)


def test_create_confluence_plugin_honours_custom_token_env(monkeypatch):
    """When ``token_env`` is overridden, the error message names the custom var."""
    monkeypatch.setenv("CONFLUENCE_EMAIL", "bot@example.com")
    monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
    monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
    cfg = {
        "base_url": "https://example.atlassian.net/wiki",
        "token_env": "ATLASSIAN_API_TOKEN",
    }
    with pytest.raises(EnvironmentError) as excinfo:
        create_plugin("confluence", cfg)
    assert "ATLASSIAN_API_TOKEN" in str(excinfo.value)
    assert "CONFLUENCE_API_TOKEN" not in str(excinfo.value)


def test_create_confluence_plugin_requires_base_url(monkeypatch):
    """``base_url`` is required — missing key raises :class:`KeyError`.

    We set the env vars first so the factory reaches the ``base_url``
    lookup rather than short-circuiting on an auth check.
    """
    monkeypatch.setenv("CONFLUENCE_EMAIL", "bot@example.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "tok-xyz")
    with pytest.raises(KeyError):
        create_plugin("confluence", {})


def test_create_confluence_plugin_threads_optional_fields(monkeypatch):
    """Optional config keys (space_keys, include_archived, concurrency, *_env) flow through."""
    monkeypatch.setenv("MY_EMAIL", "bot@example.com")
    monkeypatch.setenv("MY_TOKEN", "tok-xyz")
    cfg = {
        "base_url": "https://example.atlassian.net/wiki",
        "email_env": "MY_EMAIL",
        "token_env": "MY_TOKEN",
        "space_keys": ["ENG", "PROD"],
        "include_archived": True,
        "concurrency": 5,
    }
    plugin, _ = create_plugin("confluence", cfg)
    assert plugin.config.base_url == "https://example.atlassian.net/wiki"
    assert plugin.config.email_env == "MY_EMAIL"
    assert plugin.config.token_env == "MY_TOKEN"
    assert plugin.config.space_keys == ["ENG", "PROD"]
    assert plugin.config.include_archived is True
    assert plugin.config.concurrency == 5


def test_create_confluence_plugin_uses_default_env_var_names(monkeypatch):
    """When ``email_env``/``token_env`` are absent, defaults match the plan."""
    monkeypatch.setenv("CONFLUENCE_EMAIL", "bot@example.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "tok-xyz")
    cfg = {"base_url": "https://example.atlassian.net/wiki"}
    plugin, _ = create_plugin("confluence", cfg)
    assert plugin.config.email_env == "CONFLUENCE_EMAIL"
    assert plugin.config.token_env == "CONFLUENCE_API_TOKEN"
    # Decisions-doc locked-in default for per-source concurrency.
    assert plugin.config.concurrency == 3


# ── 6. ATL-25 — Jira factory env-var resolution ──────────────────


def test_create_jira_plugin_success_with_env_vars(monkeypatch):
    """Happy path: both env vars set → factory returns (plugin, None)."""
    from src.harvester.jira import JiraHarvesterPlugin

    monkeypatch.setenv("JIRA_EMAIL", "alice@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok-xyz")
    cfg = {
        "base_url": "https://example.atlassian.net",
        "project_keys": ["CONN"],
    }
    plugin, closeable = create_plugin("jira", cfg)
    assert isinstance(plugin, JiraHarvesterPlugin)
    # Per plan §2.2: factory returns (plugin, None) — teardown is plugin.aclose().
    assert closeable is None


def test_create_jira_plugin_success_with_inline_creds(monkeypatch):
    """Inline ``email``/``token`` in the config override env vars."""
    from src.harvester.jira import JiraHarvesterPlugin

    # Even with no env vars, inline values satisfy the factory.
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    cfg = {
        "base_url": "https://example.atlassian.net",
        "email": "alice@example.com",
        "token": "tok-xyz",
        "project_keys": ["CONN"],
    }
    plugin, _ = create_plugin("jira", cfg)
    assert isinstance(plugin, JiraHarvesterPlugin)


def test_create_jira_plugin_raises_when_email_missing(monkeypatch):
    """Missing email env var → EnvironmentError naming the offender."""
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.setenv("JIRA_API_TOKEN", "tok-xyz")
    cfg = {"base_url": "https://example.atlassian.net"}
    with pytest.raises(EnvironmentError) as excinfo:
        create_plugin("jira", cfg)
    # Message must name the env var so the remediation is obvious.
    assert "JIRA_EMAIL" in str(excinfo.value)


def test_create_jira_plugin_raises_when_token_missing(monkeypatch):
    """Missing token env var → EnvironmentError naming the offender."""
    monkeypatch.setenv("JIRA_EMAIL", "alice@example.com")
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    cfg = {"base_url": "https://example.atlassian.net"}
    with pytest.raises(EnvironmentError) as excinfo:
        create_plugin("jira", cfg)
    assert "JIRA_API_TOKEN" in str(excinfo.value)


def test_create_jira_plugin_honours_custom_email_env(monkeypatch):
    """When ``email_env`` is overridden, the error message names the custom var."""
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("ATLASSIAN_EMAIL", raising=False)
    monkeypatch.setenv("JIRA_API_TOKEN", "tok-xyz")
    cfg = {
        "base_url": "https://example.atlassian.net",
        "email_env": "ATLASSIAN_EMAIL",
    }
    with pytest.raises(EnvironmentError) as excinfo:
        create_plugin("jira", cfg)
    assert "ATLASSIAN_EMAIL" in str(excinfo.value)
    # And the default env var name must NOT appear (we correctly honoured the override).
    assert "JIRA_EMAIL" not in str(excinfo.value)


def test_create_jira_plugin_honours_custom_token_env(monkeypatch):
    """When ``token_env`` is overridden, the error message names the custom var."""
    monkeypatch.setenv("JIRA_EMAIL", "alice@example.com")
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
    cfg = {
        "base_url": "https://example.atlassian.net",
        "token_env": "ATLASSIAN_API_TOKEN",
    }
    with pytest.raises(EnvironmentError) as excinfo:
        create_plugin("jira", cfg)
    assert "ATLASSIAN_API_TOKEN" in str(excinfo.value)
    assert "JIRA_API_TOKEN" not in str(excinfo.value)


def test_create_jira_plugin_requires_base_url():
    """``base_url`` is required — missing key raises :class:`KeyError`."""
    with pytest.raises(KeyError):
        create_plugin("jira", {})
