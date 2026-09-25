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
    assert sources.ENABLED_SOURCES == ("notion", "confluence", "obsidian", "localfiles")


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
        "src.harvester.localfiles",
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


# ── harvest + scheduler gating ────────────────────────────────────
#
# A ``sources.jira`` / ``schedules.jira`` block left in someone's yaml must
# not make a hidden connector run: ``start_harvest`` skips it (and rejects an
# explicit request for it), the scheduler never registers a job for it, and
# ``has_enabled_schedules`` ignores it so it cannot pin the server up forever.

_YAML_WITH_JIRA = {
    "sources": {
        "notion": {"enabled": True},
        "jira": {"enabled": True},
    },
    "schedules": {
        "jira": {"cron": "0 3 * * *", "enabled": True},
    },
}


@pytest.fixture
def api_orchestrator(monkeypatch):
    """``src.api.orchestrator`` with config + task spawning stubbed out."""
    from src.api import orchestrator as orch

    monkeypatch.setattr(orch, "load_config_file", lambda: _YAML_WITH_JIRA)
    spawned: list[str] = []
    monkeypatch.setattr(
        orch, "_spawn_source_task", lambda source, cfg, **kw: spawned.append(source)
    )

    async def _no_watch():
        return None

    monkeypatch.setattr(orch, "_watch_run", _no_watch)
    orch.state.status = "idle"
    orch.state.sources = {}
    orch.state._tasks = {}
    yield orch, spawned
    orch.state.status = "idle"
    orch.state.sources = {}
    orch.state._tasks = {}


async def test_start_harvest_skips_a_hidden_source_from_the_yaml(monkeypatch, api_orchestrator):
    monkeypatch.delenv(sources.SOURCES_ENV, raising=False)
    orch, spawned = api_orchestrator

    result = await orch.start_harvest()

    assert result == {"ok": True, "added": 1, "running": ["notion"]}
    assert spawned == ["notion"]


async def test_start_harvest_rejects_an_explicit_request_for_a_hidden_source(
    monkeypatch, api_orchestrator
):
    monkeypatch.delenv(sources.SOURCES_ENV, raising=False)
    orch, spawned = api_orchestrator

    result = await orch.start_harvest(["jira"])

    assert result["ok"] is False
    assert "jira" in result["reason"]
    assert "not available" in result["reason"]
    assert spawned == []
    assert orch.state.status == "idle"

    # Mixed request: the hidden one poisons the whole call — nothing runs.
    result = await orch.start_harvest(["notion", "jira"])
    assert result["ok"] is False
    assert spawned == []


async def test_start_harvest_reports_nothing_to_do_when_only_hidden_sources_are_configured(
    monkeypatch, api_orchestrator
):
    from src.api import orchestrator as orch

    monkeypatch.setattr(
        orch, "load_config_file", lambda: {"sources": {"jira": {"enabled": True}}}
    )
    monkeypatch.delenv(sources.SOURCES_ENV, raising=False)
    result = await orch.start_harvest()
    assert result == {"ok": False, "reason": "no enabled sources to harvest"}


async def test_start_harvest_honours_the_env_override(monkeypatch, api_orchestrator):
    monkeypatch.setenv(sources.SOURCES_ENV, "notion,jira")
    orch, spawned = api_orchestrator

    result = await orch.start_harvest()

    assert result["ok"] is True
    assert sorted(spawned) == ["jira", "notion"]


@pytest.fixture
def scheduler_with_jira(monkeypatch):
    from src.api import scheduler

    monkeypatch.setattr(scheduler, "read_config", lambda: _YAML_WITH_JIRA)
    scheduler.stop()
    yield scheduler
    scheduler.stop()


def test_has_enabled_schedules_ignores_a_hidden_source(monkeypatch, scheduler_with_jira):
    monkeypatch.delenv(sources.SOURCES_ENV, raising=False)
    assert scheduler_with_jira.has_enabled_schedules() is False
    monkeypatch.setenv(sources.SOURCES_ENV, "notion,jira")
    assert scheduler_with_jira.has_enabled_schedules() is True


def test_reload_from_yaml_registers_no_job_for_a_hidden_source(
    monkeypatch, scheduler_with_jira, caplog
):
    import logging

    monkeypatch.delenv(sources.SOURCES_ENV, raising=False)
    logging.disable(logging.NOTSET)
    with caplog.at_level(logging.INFO, logger="src.api.scheduler"):
        scheduler_with_jira.reload_from_yaml()
    jobs = [j.id for j in scheduler_with_jira._instance().get_jobs()]
    assert jobs == []
    notices = [r for r in caplog.records if "jira" in r.getMessage()]
    assert notices and all(r.levelno == logging.INFO for r in notices)

    monkeypatch.setenv(sources.SOURCES_ENV, "notion,jira")
    scheduler_with_jira.reload_from_yaml()
    jobs = [j.id for j in scheduler_with_jira._instance().get_jobs()]
    assert jobs == ["harvest-schedule:jira"]


async def test_catch_up_skips_a_hidden_source(monkeypatch, scheduler_with_jira):
    from datetime import UTC, datetime

    monkeypatch.delenv(sources.SOURCES_ENV, raising=False)
    # Would have missed today's 03:00 run — but jira is not in this build.
    monkeypatch.setattr(scheduler_with_jira, "_last_completed", lambda s: None)
    started = []

    async def fake_start(srcs, **kw):
        started.append(srcs)
        return {"ok": True}

    monkeypatch.setattr(scheduler_with_jira.orch, "start_harvest", fake_start)
    now = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    assert await scheduler_with_jira.catch_up_missed_runs(now) == []
    assert started == []

    # Sanity: the same yaml *does* catch up once the connector is enabled.
    monkeypatch.setenv(sources.SOURCES_ENV, "notion,jira")
    assert await scheduler_with_jira.catch_up_missed_runs(now) == ["jira"]
    assert started == [["jira"]]
