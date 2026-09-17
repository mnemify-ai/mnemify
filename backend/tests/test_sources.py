"""Tests for src.sources — which connectors this build exposes.

Deliberately *not* tested here: ``registered_source_types()`` equalling the
enabled set. ``registry._PLUGIN_FACTORIES`` is process-global and permanent,
and several plugin test modules import their package at module level, so in a
full-suite run the registry legitimately holds names beyond the enabled three.
The contract that actually matters — "``_ensure_plugins_registered`` imports
only the enabled plugins" — is asserted directly against the import calls,
which is deterministic regardless of collection order.
"""

from __future__ import annotations

import pytest

from src import sources
from src.harvester import registry

# ── default set ───────────────────────────────────────────────────

def test_default_enabled_sources_are_the_three_shipped_connectors():
    assert sources.ENABLED_SOURCES == ("notion", "confluence", "obsidian")


def test_enabled_sources_returns_the_default_without_the_env_var(monkeypatch):
    monkeypatch.delenv(sources.SOURCES_ENV, raising=False)
    assert sources.enabled_sources() == sources.ENABLED_SOURCES


def test_is_enabled_covers_shipped_and_hidden_connectors(monkeypatch):
    monkeypatch.delenv(sources.SOURCES_ENV, raising=False)
    for name in ("notion", "confluence", "obsidian"):
        assert sources.is_enabled(name), name
    for name in sources.EXPERIMENTAL_SOURCES:
        assert not sources.is_enabled(name), name


def test_experimental_and_enabled_sets_do_not_overlap():
    assert not set(sources.ENABLED_SOURCES) & set(sources.EXPERIMENTAL_SOURCES)


# ── MNEMIFY_SOURCES override ──────────────────────────────────────

def test_env_override_replaces_the_set(monkeypatch):
    monkeypatch.setenv(sources.SOURCES_ENV, "notion,jira,slack")
    assert sources.enabled_sources() == ("notion", "jira", "slack")
    assert sources.is_enabled("jira")
    assert not sources.is_enabled("confluence")


def test_env_override_tolerates_whitespace_and_empty_entries(monkeypatch):
    monkeypatch.setenv(sources.SOURCES_ENV, "  notion , , obsidian ,")
    assert sources.enabled_sources() == ("notion", "obsidian")


def test_blank_env_override_falls_back_to_the_default(monkeypatch):
    # An empty value reads as a typo, not as "ship zero connectors" — a build
    # with no sources at all is never what anyone means.
    monkeypatch.setenv(sources.SOURCES_ENV, "   ")
    assert sources.enabled_sources() == sources.ENABLED_SOURCES


def test_override_is_read_at_call_time_not_import_time(monkeypatch):
    monkeypatch.setenv(sources.SOURCES_ENV, "github")
    assert sources.enabled_sources() == ("github",)
    monkeypatch.setenv(sources.SOURCES_ENV, "gmail")
    assert sources.enabled_sources() == ("gmail",)


# ── registry wiring ───────────────────────────────────────────────

@pytest.fixture
def recorded_imports(monkeypatch):
    """Capture the module names ``_ensure_plugins_registered`` asks for.

    Patching ``registry._try_import`` rather than inspecting
    ``registered_source_types()`` keeps the assertion independent of what any
    other test module already imported into the process-global registry.
    """
    calls: list[str] = []
    monkeypatch.setattr(registry, "_try_import", calls.append)
    return calls


def test_registry_imports_only_the_enabled_plugins(monkeypatch, recorded_imports):
    monkeypatch.delenv(sources.SOURCES_ENV, raising=False)
    registry._ensure_plugins_registered()
    assert recorded_imports == [
        "src.harvester.notion",
        "src.harvester.confluence",
        "src.harvester.obsidian",
    ]


def test_registry_never_imports_a_hidden_plugin(monkeypatch, recorded_imports):
    monkeypatch.delenv(sources.SOURCES_ENV, raising=False)
    registry._ensure_plugins_registered()
    for name in sources.EXPERIMENTAL_SOURCES:
        assert f"src.harvester.{name}" not in recorded_imports


def test_registry_follows_the_env_override(monkeypatch, recorded_imports):
    monkeypatch.setenv(sources.SOURCES_ENV, "notion,slack")
    registry._ensure_plugins_registered()
    assert recorded_imports == ["src.harvester.notion", "src.harvester.slack"]


def test_shipped_connectors_are_actually_registered():
    # Superset assertion only — see this module's docstring.
    types = registry.registered_source_types()
    for name in sources.ENABLED_SOURCES:
        assert name in types, name
