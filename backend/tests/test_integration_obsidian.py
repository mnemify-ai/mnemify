"""Integration test — full Obsidian harvest run against the fixture vault.

Runs end-to-end through the real orchestrator: plugin -> manifest ->
raw_store -> logger.  No network required; all reads come from the local
fixture vault at tests/fixtures/obsidian-vault/.

What it tests:
  1. Plugin connection health check passes.
  2. list_documents() returns the expected set of notes.
  3. Full orchestrator run writes raw .md files to the raw store.
  4. Manifest rows are created with correct source_type, raw_path, and format.
  5. JSONL log contains harvest_started / harvested / harvest_completed events.
  6. Second orchestrator run with same content reports all docs unchanged.
  7. Raw file mtimes do not change on the second run.
  8. Deletion detection marks a note as deleted_at_source when it disappears.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.harvester.logger import HarvestLogger
from src.harvester.manifest import HarvestManifest
from src.harvester.obsidian.models import ObsidianVaultConfig
from src.harvester.obsidian.plugin import ObsidianHarvesterPlugin
from src.harvester.orchestrator import HarvestOrchestrator, WriteBackConfig
from src.harvester.raw_store import RawStore

VAULT = Path(__file__).parent / "fixtures" / "obsidian-vault"


@pytest.fixture
def vault_plugin() -> ObsidianHarvesterPlugin:
    cfg = ObsidianVaultConfig(
        vault_path=str(VAULT),
        ignore_patterns=["templates/*", "02-wiki/*"],
    )
    return ObsidianHarvesterPlugin(cfg)


# ── 1. Health check ────────────────────────────────────────────────

async def test_connection_to_fixture_vault_is_healthy(vault_plugin):
    health = await vault_plugin.test_connection()
    assert health.healthy, f"Health check failed: {health.message}"


# ── 2. list_documents returns expected notes ───────────────────────

async def test_list_documents_returns_all_expected_notes(vault_plugin):
    docs = await vault_plugin.list_documents()
    paths = {d.metadata["relative_path"] for d in docs}

    expected = {
        "00-inbox/quick-note.md",
        "00-inbox/web-clip.md",
        "daily/2026-04-15.md",
        "meetings/q2-planning.md",
        "notes/project-mnemify.md",
        "notes/nested/deep-note.md",
    }
    for path in expected:
        assert path in paths, f"Expected note not found: {path}"

    # These should be excluded by ignore_patterns
    assert "templates/daily-template.md" not in paths
    assert "02-wiki/compiled-output.md" not in paths


# ── 3-7. Full orchestrator run ─────────────────────────────────────

async def test_orchestrator_full_run_writes_md_raw_files(vault_plugin, tmp_path):
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "harvest.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = HarvestOrchestrator(
        plugin=vault_plugin,
        manifest=manifest,
        harvest_logger=log,
        max_concurrent=2,
        raw_store=raw_store,
        write_back=WriteBackConfig(enabled=False),
    )

    result = await orch.run(source_type="obsidian", mode="on_demand")

    assert result.found > 0
    assert result.harvested > 0
    assert result.failed == 0

    # Raw files should be .md (not .json)
    raw_files = list((tmp_path / "raw").rglob("*.md"))
    assert len(raw_files) > 0, "Expected at least one .md raw file"


async def test_orchestrator_manifest_rows_have_correct_format(vault_plugin, tmp_path):
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "harvest.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = HarvestOrchestrator(
        plugin=vault_plugin,
        manifest=manifest,
        harvest_logger=log,
        max_concurrent=2,
        raw_store=raw_store,
    )

    await orch.run(source_type="obsidian", mode="on_demand")

    docs = manifest.get_documents("obsidian", status="active")
    assert len(docs) > 0

    for row in docs:
        assert row["source_type"] == "obsidian"
        assert row["raw_format"] == "md"
        assert row["raw_path"] is not None
        assert row["raw_path"].endswith(".md")
        assert row["content_hash"] is not None


async def test_orchestrator_jsonl_log_has_expected_events(vault_plugin, tmp_path):
    manifest = HarvestManifest(":memory:")
    log_path = tmp_path / "harvest.jsonl"
    log = HarvestLogger(log_path)
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    orch = HarvestOrchestrator(
        plugin=vault_plugin,
        manifest=manifest,
        harvest_logger=log,
        max_concurrent=2,
        raw_store=raw_store,
    )

    await orch.run(source_type="obsidian", mode="on_demand")

    entries = log.read_log()
    actions = [e["action"] for e in entries]
    assert "harvest_started" in actions
    assert "harvested" in actions
    assert "harvest_completed" in actions


async def test_orchestrator_second_run_all_unchanged(vault_plugin, tmp_path):
    """Run the orchestrator twice against the same vault.  Second run must
    report everything unchanged and not rewrite raw files."""
    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "harvest.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    def make_orch():
        return HarvestOrchestrator(
            plugin=vault_plugin,
            manifest=manifest,
            harvest_logger=log,
            max_concurrent=2,
            raw_store=raw_store,
            force_full=True,  # always list all docs
        )

    result1 = await make_orch().run(source_type="obsidian", mode="on_demand")
    assert result1.harvested > 0

    raw_files = list((tmp_path / "raw").rglob("*.md"))
    mtimes_before = {f: f.stat().st_mtime for f in raw_files}

    result2 = await make_orch().run(source_type="obsidian", mode="on_demand")

    assert result2.harvested == 0, (
        f"Expected 0 harvested on second run, got {result2.harvested}"
    )
    assert result2.skipped > 0

    for f, mtime in mtimes_before.items():
        assert f.stat().st_mtime == mtime, f"Raw file {f} was rewritten on second run"


# ── 9. Deletion detection ──────────────────────────────────────────

async def test_deletion_detection_marks_missing_note(tmp_path):
    """Simulate a note disappearing between runs."""
    import shutil

    # Copy vault to a temp dir so we can modify it
    vault_copy = tmp_path / "vault"
    shutil.copytree(str(VAULT), str(vault_copy))

    cfg = ObsidianVaultConfig(vault_path=str(vault_copy))
    plugin = ObsidianHarvesterPlugin(cfg)

    manifest = HarvestManifest(":memory:")
    log = HarvestLogger(tmp_path / "harvest.jsonl")
    raw_store = RawStore(tmp_path / "raw", converter_version="0.1.0")

    def make_orch(p):
        return HarvestOrchestrator(
            plugin=p,
            manifest=manifest,
            harvest_logger=log,
            max_concurrent=2,
            raw_store=raw_store,
            force_full=True,
        )

    # First run — harvest everything
    result1 = await make_orch(plugin).run(source_type="obsidian", mode="on_demand")
    assert result1.harvested > 0

    # Delete a note
    note_to_delete = vault_copy / "00-inbox" / "quick-note.md"
    note_to_delete.unlink()

    # Second run — deleted note should be detected
    plugin2 = ObsidianHarvesterPlugin(cfg)
    result2 = await make_orch(plugin2).run(source_type="obsidian", mode="on_demand")
    assert result2.deleted == 1

    # Confirm manifest status
    deleted_rows = manifest.get_documents("obsidian", status="deleted_at_source")
    assert len(deleted_rows) == 1
