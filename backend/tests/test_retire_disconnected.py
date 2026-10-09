"""A disconnected source's documents leave the next compile.

Harvests skip disabled sources, so the scope-aware reconcile never reaches
their docs; ``retire_disconnected_sources`` parks them as ``out_of_scope``
and a later harvest that sees them again brings them back.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src import paths
from src.api import orchestrator as harvest_orch
from src.harvester.manifest import HarvestManifest
from src.harvester.orchestrator import DocRef, _doc_already_harvested

DT1 = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)


def _manifest() -> HarvestManifest:
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    return HarvestManifest(paths.data_dir() / "harvest-manifest.db")


def _write_yaml(text: str) -> None:
    paths.yaml_file().write_text(text, encoding="utf-8")


def test_retire_source_marks_only_that_sources_active_docs():
    m = HarvestManifest(":memory:")
    m.upsert_document("localfiles", "a", "A")
    m.upsert_document("confluence", "b", "B")

    assert m.retire_source("localfiles") == 1
    assert m.lookup("localfiles", "a")["harvest_status"] == "out_of_scope"
    assert m.lookup("confluence", "b")["harvest_status"] == "active"
    assert m.active_source_types() == {"confluence"}


def test_unchanged_upsert_reactivates_a_retired_doc():
    m = HarvestManifest(":memory:")
    m.upsert_document("localfiles", "a", "A", content_hash="h", source_modified=DT1)
    m.retire_source("localfiles")

    _, action = m.upsert_document("localfiles", "a", "A", content_hash="h", source_modified=DT1)

    assert action == "unchanged"
    assert m.lookup("localfiles", "a")["harvest_status"] == "active"


def test_retired_doc_is_not_short_circuited_by_the_resume_check():
    ref = DocRef(source_type="localfiles", source_id="a", title="A", modified_at=DT1)
    row = {"raw_path": "x", "source_modified": DT1.isoformat(), "harvest_status": "active"}
    assert _doc_already_harvested(ref, row)
    assert not _doc_already_harvested(ref, {**row, "harvest_status": "out_of_scope"})


def test_retire_disconnected_sources_follows_the_yaml():
    _write_yaml(
        "sources:\n"
        "  confluence:\n    enabled: true\n"
        "  localfiles:\n    enabled: false\n    roots: []\n"
    )
    m = _manifest()
    m.upsert_document("localfiles", "a", "A")
    m.upsert_document("confluence", "b", "B")
    m.upsert_document("notion", "c", "C")  # block missing entirely
    m.close()

    assert harvest_orch.retire_disconnected_sources() == {"localfiles": 1, "notion": 1}

    m = _manifest()
    assert m.active_source_types() == {"confluence"}
    m.close()
    # Idempotent.
    assert harvest_orch.retire_disconnected_sources() == {}


def test_retire_disconnected_sources_without_a_manifest_is_a_noop():
    assert harvest_orch.retire_disconnected_sources() == {}
