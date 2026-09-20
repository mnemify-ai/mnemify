"""``PRAGMA user_version`` on the two SQLite stores.

Protects the user who juggles two checkouts (or downgrades after pulling a
newer main): a database written by a newer Mnemify must refuse to open rather
than be silently half-read.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.harvester.manifest import HarvestManifest
from src.terrain.utils.store import TerrainStore

STORES = [
    pytest.param(HarvestManifest, "harvest-manifest.db", id="manifest"),
    pytest.param(TerrainStore, "terrain.db", id="terrain"),
]


def _user_version(path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def _set_user_version(path, value: int) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(f"PRAGMA user_version = {value}")
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("cls,name", STORES)
def test_a_fresh_database_is_stamped(tmp_path, cls, name):
    db = tmp_path / name
    store = cls(db)
    store.close()
    assert _user_version(db) == cls.SCHEMA_VERSION == 1


@pytest.mark.parametrize("cls,name", STORES)
def test_reopening_keeps_the_stamp(tmp_path, cls, name):
    db = tmp_path / name
    cls(db).close()
    cls(db).close()
    assert _user_version(db) == cls.SCHEMA_VERSION


@pytest.mark.parametrize("cls,name", STORES)
def test_a_newer_database_refuses_to_open(tmp_path, cls, name):
    db = tmp_path / name
    cls(db).close()
    _set_user_version(db, 99)

    with pytest.raises(RuntimeError) as excinfo:
        cls(db)
    message = str(excinfo.value)
    assert "newer Mnemify" in message
    assert "schema v99" in message
    assert str(db) in message


@pytest.mark.parametrize("cls,name", STORES)
def test_an_unversioned_database_is_upgraded_without_data_loss(tmp_path, cls, name):
    """The realistic case: every DB written before this stamp existed reads
    back as ``user_version == 0``. It must migrate in place, not be refused
    and not be recreated."""
    db = tmp_path / name
    store = cls(db)
    store.close()
    # Pretend it predates the stamp, and leave a row behind to prove the
    # migration path doesn't blow the file away.
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE IF NOT EXISTS _canary (id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO _canary (id) VALUES ('keep-me')")
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()

    store = cls(db)
    try:
        row = store._conn.execute("SELECT id FROM _canary").fetchone()
        assert row[0] == "keep-me"
    finally:
        store.close()
    assert _user_version(db) == cls.SCHEMA_VERSION


def test_manifest_keeps_real_rows_across_an_unversioned_upgrade(tmp_path):
    """End-to-end on the manifest's own tables, not just a canary."""
    db = tmp_path / "harvest-manifest.db"
    manifest = HarvestManifest(db)
    manifest.upsert_document(
        "notion",
        "doc-1",
        "Hello",
        source_url="https://example.com/1",
        content_hash="abc",
        raw_path="notion/doc-1.json",
    )
    manifest.close()

    _set_user_version(db, 0)

    manifest = HarvestManifest(db)
    try:
        doc = manifest.lookup("notion", "doc-1")
        assert doc is not None
        assert doc["title"] == "Hello"
    finally:
        manifest.close()
    assert _user_version(db) == HarvestManifest.SCHEMA_VERSION
