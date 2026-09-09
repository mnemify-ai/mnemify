"""Unit tests for HarvestManifest (src/harvester/manifest.py)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from src.harvester.manifest import HarvestManifest

logger = logging.getLogger(__name__)


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def db() -> HarvestManifest:
    """In-memory SQLite manifest — isolated per test."""
    return HarvestManifest(":memory:")


DT1 = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
DT2 = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)
DT3 = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)

HASH_A = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa0001"
HASH_B = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb0002"


# ── Schema initialisation ──────────────────────────────────────────

def test_schema_creates_documents_and_runs_tables(db):
    row = db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    tables = {r[0] for r in row}
    assert "documents" in tables
    assert "harvest_runs" in tables


def test_documents_table_has_bytes_columns(db):
    cols = {r["name"] for r in db._conn.execute("PRAGMA table_info(documents)")}
    assert "raw_bytes" in cols
    assert "normalized_bytes" in cols


def test_set_raw_path_records_raw_bytes(db):
    db.upsert_document("notion", "page-1", "T", content_hash=HASH_A)
    db.set_raw_path("notion", "page-1", "/some/raw/path.json", raw_bytes=1024)
    row = db.lookup("notion", "page-1")
    assert row["raw_path"] == "/some/raw/path.json"
    assert row["raw_bytes"] == 1024


def test_set_raw_path_without_bytes_leaves_raw_bytes_null(db):
    db.upsert_document("notion", "page-1", "T", content_hash=HASH_A)
    db.set_raw_path("notion", "page-1", "/some/raw/path.json")
    row = db.lookup("notion", "page-1")
    assert row["raw_path"] == "/some/raw/path.json"
    assert row["raw_bytes"] is None


def test_set_normalized_path_records_normalized_bytes(db):
    db.upsert_document("notion", "page-1", "T", content_hash=HASH_A)
    db.set_normalized_path(
        "notion",
        "page-1",
        "/some/normalized/path.md",
        normalizer_version="0.2.0",
        normalized_bytes=512,
    )
    row = db.lookup("notion", "page-1")
    assert row["normalized_path"] == "/some/normalized/path.md"
    assert row["normalized_format"] == "md"
    assert row["normalizer_version"] == "0.2.0"
    assert row["normalized_bytes"] == 512


# ── Lookup ─────────────────────────────────────────────────────────

def test_looking_up_nonexistent_document_returns_none(db):
    assert db.lookup("notion", "nonexistent") is None


def test_lookup_returns_row_after_insert(db):
    db.upsert_document("notion", "page-1", "My Page", content_hash=HASH_A, source_modified=DT1)
    row = db.lookup("notion", "page-1")
    assert row is not None
    assert row["source_id"] == "page-1"
    assert row["title"] == "My Page"


# ── Insert: new documents ──────────────────────────────────────────

def test_first_insert_returns_new_action(db):
    doc_id, action = db.upsert_document("notion", "page-1", "Title", content_hash=HASH_A)
    assert action == "new"
    assert doc_id  # non-empty UUID


def test_upsert_new_doc_stored_with_version_1(db):
    db.upsert_document("notion", "page-1", "Title")
    row = db.lookup("notion", "page-1")
    assert row["version"] == 1
    assert row["harvest_status"] == "active"


def test_upsert_new_doc_stores_all_fields(db):
    db.upsert_document(
        "notion", "page-1", "My Page",
        source_url="https://example.com",
        content_hash=HASH_A,
        source_modified=DT1,
        converter_version="0.1.0",
        metadata={"parent_id": "db-1"},
    )
    row = db.lookup("notion", "page-1")
    assert row["source_url"] == "https://example.com"
    assert row["content_hash"] == HASH_A
    assert row["converter_version"] == "0.1.0"


# ── Update: unchanged detection ────────────────────────────────────

def test_same_content_hash_with_different_timestamp_is_unchanged(db):
    db.upsert_document("notion", "page-1", "Title", content_hash=HASH_A, source_modified=DT1)
    # Same hash, different timestamp (timestamp noise)
    _, action = db.upsert_document("notion", "page-1", "Title", content_hash=HASH_A, source_modified=DT2)
    assert action == "unchanged"


def test_upsert_same_timestamp_returns_unchanged(db):
    db.upsert_document("notion", "page-1", "Title", content_hash=HASH_A, source_modified=DT1)
    _, action = db.upsert_document("notion", "page-1", "Title", content_hash=HASH_B, source_modified=DT1)
    assert action == "unchanged"


def test_upsert_unchanged_does_not_increment_version(db):
    db.upsert_document("notion", "page-1", "Title", content_hash=HASH_A, source_modified=DT1)
    db.upsert_document("notion", "page-1", "Title", content_hash=HASH_A, source_modified=DT2)
    row = db.lookup("notion", "page-1")
    assert row["version"] == 1


# ── Update: genuine content change ────────────────────────────────

def test_different_hash_and_newer_timestamp_is_updated(db):
    db.upsert_document("notion", "page-1", "Title", content_hash=HASH_A, source_modified=DT1)
    _, action = db.upsert_document("notion", "page-1", "Title", content_hash=HASH_B, source_modified=DT2)
    assert action == "updated"


def test_genuine_update_increments_document_version(db):
    db.upsert_document("notion", "page-1", "Title", content_hash=HASH_A, source_modified=DT1)
    db.upsert_document("notion", "page-1", "Title", content_hash=HASH_B, source_modified=DT2)
    row = db.lookup("notion", "page-1")
    assert row["version"] == 2


def test_upsert_updated_multiple_times_increments_each_time(db):
    db.upsert_document("notion", "p", "T", content_hash=HASH_A, source_modified=DT1)
    db.upsert_document("notion", "p", "T", content_hash=HASH_B, source_modified=DT2)
    db.upsert_document("notion", "p", "T", content_hash=HASH_A, source_modified=DT3)
    row = db.lookup("notion", "p")
    assert row["version"] == 3


def test_upsert_updated_resets_harvest_status_to_active(db):
    db.upsert_document("notion", "page-1", "Title", content_hash=HASH_A, source_modified=DT1)
    # Simulate it being marked deleted
    db._conn.execute(
        "UPDATE documents SET harvest_status='deleted_at_source' WHERE source_id='page-1'"
    )
    db._conn.commit()
    db.upsert_document("notion", "page-1", "Title", content_hash=HASH_B, source_modified=DT2)
    row = db.lookup("notion", "page-1")
    assert row["harvest_status"] == "active"


# ── Deletion tracking ──────────────────────────────────────────────

def test_pages_missing_from_source_are_marked_deleted(db):
    db.upsert_document("notion", "page-1", "A")
    db.upsert_document("notion", "page-2", "B")
    db.upsert_document("notion", "page-3", "C")

    deleted = db.mark_deleted("notion", active_source_ids={"page-1", "page-3"})

    assert "page-2" in deleted
    assert len(deleted) == 1
    row = db.lookup("notion", "page-2")
    assert row["harvest_status"] == "deleted_at_source"


def test_mark_deleted_does_not_touch_still_active_docs(db):
    db.upsert_document("notion", "page-1", "A")
    db.mark_deleted("notion", active_source_ids={"page-1"})
    row = db.lookup("notion", "page-1")
    assert row["harvest_status"] == "active"


def test_mark_deleted_returns_empty_when_none_missing(db):
    db.upsert_document("notion", "page-1", "A")
    result = db.mark_deleted("notion", active_source_ids={"page-1"})
    assert result == []


# ── get_documents ──────────────────────────────────────────────────

def test_get_documents_returns_active_by_default(db):
    db.upsert_document("notion", "p1", "A")
    db.upsert_document("notion", "p2", "B")
    docs = db.get_documents("notion")
    assert len(docs) == 2


def test_get_documents_filters_by_status(db):
    db.upsert_document("notion", "p1", "A")
    db.upsert_document("notion", "p2", "B")
    db.mark_deleted("notion", active_source_ids={"p1"})
    active = db.get_documents("notion", status="active")
    deleted = db.get_documents("notion", status="deleted_at_source")
    assert len(active) == 1
    assert len(deleted) == 1


def test_get_documents_no_source_type_returns_all(db):
    db.upsert_document("notion", "n1", "N")
    db.upsert_document("confluence", "c1", "C")
    docs = db.get_documents()
    assert len(docs) == 2


# ── Converter version query ────────────────────────────────────────

def test_get_documents_by_converter_version(db):
    db.upsert_document("notion", "p1", "A", converter_version="0.1.0")
    db.upsert_document("notion", "p2", "B", converter_version="0.2.0")
    db.upsert_document("notion", "p3", "C", converter_version="0.3.0")
    stale = db.get_documents_by_converter_version("notion", below_version="0.3.0")
    ids = {r["source_id"] for r in stale}
    assert ids == {"p1", "p2"}


# ── Harvest runs ───────────────────────────────────────────────────

def test_start_run_returns_run_id(db):
    run_id = db.start_run(source_type="notion", mode="scheduled")
    assert run_id.startswith("run_")


def test_complete_run_stores_stats(db):
    run_id = db.start_run("notion", "scheduled")
    db.complete_run(run_id, {"found": 10, "harvested": 3, "skipped": 7, "failed": 0})
    run = db.get_run(run_id)
    assert run["docs_found"] == 10
    assert run["docs_harvested"] == 3
    assert run["docs_skipped"] == 7
    assert run["docs_failed"] == 0
    assert run["completed_at"] is not None


def test_complete_run_stores_errors_as_json(db):
    run_id = db.start_run()
    db.complete_run(run_id, {"errors": ["err1", "err2"]})
    run = db.get_run(run_id)
    import json
    errors = json.loads(run["errors"])
    assert errors == ["err1", "err2"]


def test_get_run_returns_none_for_missing(db):
    assert db.get_run("run_nonexistent") is None


# ── Last harvest time ──────────────────────────────────────────────

def test_get_last_harvest_time_returns_none_when_no_runs(db):
    assert db.get_last_harvest_time("notion") is None


def test_get_last_harvest_time_returns_most_recent_completed(db):
    run1 = db.start_run("notion")
    db.complete_run(run1, {})
    run2 = db.start_run("notion")
    db.complete_run(run2, {})
    dt = db.get_last_harvest_time("notion")
    assert dt is not None
    assert isinstance(dt, datetime)


def test_get_last_harvest_time_ignores_incomplete_runs(db):
    db.start_run("notion")  # not completed — no complete_run call
    assert db.get_last_harvest_time("notion") is None


def test_get_last_harvest_time_is_source_scoped(db):
    run = db.start_run("notion")
    db.complete_run(run, {})
    assert db.get_last_harvest_time("confluence") is None


# ── Stats ──────────────────────────────────────────────────────────

def test_stats_reflect_total_documents_across_sources(db):
    db.upsert_document("notion", "n1", "N")
    db.upsert_document("notion", "n2", "N2")
    db.upsert_document("confluence", "c1", "C")
    s = db.stats()
    assert s["total_documents"] == 3
    assert s["total_runs"] == 0


def test_stats_by_source_breakdown(db):
    db.upsert_document("notion", "n1", "N")
    db.upsert_document("confluence", "c1", "C")
    s = db.stats()
    sources = {r["source_type"] for r in s["by_source"]}
    assert "notion" in sources
    assert "confluence" in sources
