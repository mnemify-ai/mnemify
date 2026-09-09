"""Harvest manifest — SQLite-backed state store for incremental harvesting.

HarvestManifest tracks every document the system has seen, enabling:
  - Incremental sync: skip unchanged documents (timestamp → hash gate)
  - Change detection: distinguish real content changes from metadata-only edits
  - Deletion tracking: detect pages removed from the source
  - Run history: stats and timing for each harvest run
  - Converter versioning: re-process documents when the pipeline improves

The manifest does NOT touch the raw folder (file paths are stored as nullable
strings and filled in later when the storage layer is built).

Typical usage by an orchestrator:

    manifest = HarvestManifest(".mnemify/harvest-manifest.db")
    logger   = HarvestLogger(".mnemify/harvest-log.jsonl")

    run_id = manifest.start_run(source_type="notion", mode="scheduled")
    since  = manifest.get_last_harvest_time("notion")

    docs    = await plugin.list_documents(since=since)

    stats = {"found": len(docs), "harvested": 0, "skipped": 0, "failed": 0}
    for doc_ref in docs:
        raw = await plugin.fetch_document(doc_ref)
        content_hash = sha256_hash(raw.content)
        doc_id, action = manifest.upsert_document(
            source_type="notion",
            source_id=doc_ref.source_id,
            title=doc_ref.title,
            source_url=doc_ref.source_url,
            content_hash=content_hash,
            source_modified=doc_ref.modified_at,
        )
        if action == "unchanged":
            stats["skipped"] += 1
        else:
            stats["harvested"] += 1

    manifest.complete_run(run_id, stats)
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    # Handle both offset-aware (Z / +HH:MM) and naive ISO 8601
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class HarvestManifest:
    """SQLite-backed manifest tracking harvested documents and run history.

    The database is created (with all tables) on first use if it doesn't exist.
    All write operations are wrapped in transactions; reads use autocommit.
    """

    _DOCUMENTS_DDL = """
    CREATE TABLE IF NOT EXISTS documents (
        id                 TEXT PRIMARY KEY,
        source_type        TEXT NOT NULL,
        source_id          TEXT NOT NULL,
        source_url         TEXT,
        title              TEXT,
        content_hash       TEXT,
        source_modified    TEXT,
        harvested_at       TEXT NOT NULL,
        raw_path           TEXT,
        raw_format         TEXT,
        normalized_path    TEXT,
        normalized_format  TEXT,
        normalizer_version TEXT,
        version            INTEGER NOT NULL DEFAULT 1,
        converter_version  TEXT,
        harvest_status     TEXT NOT NULL DEFAULT 'active',
        metadata           TEXT NOT NULL DEFAULT '{}',
        UNIQUE(source_type, source_id)
    );
    """

    # Columns added after the initial schema. ``_init_schema`` checks
    # ``PRAGMA table_info`` and issues idempotent ``ALTER TABLE`` for each.
    _DOCUMENTS_MIGRATIONS: list[tuple[str, str]] = [
        ("normalized_path", "ALTER TABLE documents ADD COLUMN normalized_path TEXT"),
        ("normalized_format", "ALTER TABLE documents ADD COLUMN normalized_format TEXT"),
        ("normalizer_version", "ALTER TABLE documents ADD COLUMN normalizer_version TEXT"),
        ("raw_bytes", "ALTER TABLE documents ADD COLUMN raw_bytes INTEGER"),
        ("normalized_bytes", "ALTER TABLE documents ADD COLUMN normalized_bytes INTEGER"),
        # Scope-aware deletion (Option B): the scope key the doc was harvested
        # under. NULL on rows from before this column existed — mark_deleted
        # treats NULL as "unknown origin, fall back to the legacy heuristic"
        # so old data doesn't get auto-archived on the next run.
        ("origin_scope_id", "ALTER TABLE documents ADD COLUMN origin_scope_id TEXT"),
        # ISO 8601 timestamp of the most recent ``harvest_status`` transition.
        # Lets the retention sweep purge docs marked ``deleted_at_source``
        # more than N days ago without burning the grace period for rows
        # that were already deleted before this column existed (NULL falls
        # back to ``harvested_at`` at query time — best-effort, but those
        # rows will be purgeable once a future status flip stamps them).
        ("status_changed_at", "ALTER TABLE documents ADD COLUMN status_changed_at TEXT"),
    ]

    # Per-source state — the scope ids that were in YAML at the end of the
    # most recent successful (non-scoped) harvest run for this source. The
    # Connections card uses this to compute "items added since last harvest"
    # as a stable set diff, instead of guessing from doc counts (which broke
    # for empty scopes, legacy rows missing ``origin_scope_id``, and runs
    # still in progress).
    _SOURCE_STATE_DDL = """
    CREATE TABLE IF NOT EXISTS source_state (
        source_type        TEXT PRIMARY KEY,
        last_scope_snapshot TEXT,
        updated_at         TEXT NOT NULL
    );
    """

    _HARVEST_RUNS_DDL = """
    CREATE TABLE IF NOT EXISTS harvest_runs (
        id              TEXT PRIMARY KEY,
        started_at      TEXT NOT NULL,
        completed_at    TEXT,
        source_type     TEXT,
        mode            TEXT NOT NULL DEFAULT 'scheduled',
        docs_found      INTEGER NOT NULL DEFAULT 0,
        docs_harvested  INTEGER NOT NULL DEFAULT 0,
        docs_skipped    INTEGER NOT NULL DEFAULT 0,
        docs_failed     INTEGER NOT NULL DEFAULT 0,
        errors          TEXT NOT NULL DEFAULT '[]'
    );
    """

    # Columns added to ``harvest_runs`` after its initial schema. Applied the
    # same idempotent ``PRAGMA table_info`` + ``ALTER TABLE`` way as
    # ``_DOCUMENTS_MIGRATIONS``.
    _HARVEST_RUNS_MIGRATIONS: list[tuple[str, str]] = [
        # JSON object of content-level extraction drops aggregated by kind →
        # count (e.g. ``{"notion_unsupported_block": 14}``). Distinct from
        # ``errors`` (whole-doc failures): the doc was harvested but some of
        # its blocks/comments/nodes couldn't be rendered.
        (
            "warnings",
            "ALTER TABLE harvest_runs ADD COLUMN warnings TEXT NOT NULL DEFAULT '{}'",
        ),
    ]

    def __init__(self, db_path: str | Path = ".mnemify/harvest-manifest.db"):
        self.db_path = Path(db_path)
        if self.db_path != Path(":memory:"):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._transaction():
            self._conn.execute(self._DOCUMENTS_DDL)
            self._conn.execute(self._HARVEST_RUNS_DDL)
            self._conn.execute(self._SOURCE_STATE_DDL)
            existing_cols = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(documents)")
            }
            for col_name, ddl in self._DOCUMENTS_MIGRATIONS:
                if col_name not in existing_cols:
                    self._conn.execute(ddl)
            existing_run_cols = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(harvest_runs)")
            }
            for col_name, ddl in self._HARVEST_RUNS_MIGRATIONS:
                if col_name not in existing_run_cols:
                    self._conn.execute(ddl)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    # ── Document operations ────────────────────────────────────────

    def lookup(self, source_type: str, source_id: str) -> dict | None:
        """Find an existing document entry.

        Returns:
            A plain dict of the row, or None if not found.
        """
        row = self._conn.execute(
            "SELECT * FROM documents WHERE source_type = ? AND source_id = ?",
            (source_type, source_id),
        ).fetchone()
        return dict(row) if row else None

    def lookup_by_id(self, doc_id: str) -> dict | None:
        """Find a document row by its primary-key ``id``.

        Used by the per-doc reharvest endpoint, which receives the
        manifest row id from the UI.
        """
        row = self._conn.execute(
            "SELECT * FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        return dict(row) if row else None

    def upsert_document(
        self,
        source_type: str,
        source_id: str,
        title: str,
        *,
        source_url: str | None = None,
        content_hash: str | None = None,
        source_modified: datetime | str | None = None,
        raw_path: str | None = None,
        raw_format: str | None = None,
        converter_version: str | None = None,
        metadata: dict | None = None,
        origin_scope_id: str | None = None,
    ) -> tuple[str, str]:
        """Insert or update a document entry with full change detection.

        Change detection flow:
        1. If no existing entry → insert as new.
        2. If existing entry and source_modified unchanged → "unchanged" (skip).
        3. If source_modified changed but content_hash matches → "unchanged"
           (timestamp changed but content didn't, e.g. Notion permission edit).
        4. If source_modified changed and content_hash differs → "updated".

        Returns:
            (doc_id, action) where action is "new" | "updated" | "unchanged".
        """
        # Normalise source_modified to ISO string
        if isinstance(source_modified, datetime):
            source_modified = source_modified.isoformat()

        now = _now_iso()
        existing = self.lookup(source_type, source_id)

        if existing is None:
            doc_id = str(uuid.uuid4())
            with self._transaction():
                self._conn.execute(
                    """
                    INSERT INTO documents
                        (id, source_type, source_id, source_url, title,
                         content_hash, source_modified, harvested_at,
                         raw_path, raw_format, version, converter_version,
                         harvest_status, metadata, origin_scope_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,1,?,'active',?,?)
                    """,
                    (
                        doc_id, source_type, source_id, source_url, title,
                        content_hash, source_modified, now,
                        raw_path, raw_format, converter_version,
                        json.dumps(metadata or {}),
                        origin_scope_id,
                    ),
                )
            return doc_id, "new"

        # ── Existing entry — check if content really changed ───────
        doc_id = existing["id"]
        prev_modified = existing["source_modified"]
        prev_hash = existing["content_hash"]

        # Primary gate: source timestamp
        if source_modified and prev_modified and source_modified <= prev_modified:
            return doc_id, "unchanged"

        # Secondary gate: content hash (catches timestamp-only noise)
        if content_hash and prev_hash and content_hash == prev_hash:
            return doc_id, "unchanged"

        # Genuine update
        new_version = (existing["version"] or 1) + 1
        with self._transaction():
            self._conn.execute(
                """
                UPDATE documents SET
                    source_url        = COALESCE(?, source_url),
                    title             = ?,
                    content_hash      = COALESCE(?, content_hash),
                    source_modified   = COALESCE(?, source_modified),
                    harvested_at      = ?,
                    raw_path          = COALESCE(?, raw_path),
                    raw_format        = COALESCE(?, raw_format),
                    version           = ?,
                    converter_version = COALESCE(?, converter_version),
                    harvest_status    = 'active',
                    metadata          = COALESCE(?, metadata),
                    origin_scope_id   = COALESCE(?, origin_scope_id)
                WHERE id = ?
                """,
                (
                    source_url, title,
                    content_hash, source_modified, now,
                    raw_path, raw_format, new_version,
                    converter_version,
                    json.dumps(metadata) if metadata is not None else None,
                    origin_scope_id,
                    doc_id,
                ),
            )
        return doc_id, "updated"

    def set_raw_path(
        self,
        source_type: str,
        source_id: str,
        raw_path: str,
        *,
        raw_bytes: int | None = None,
    ) -> None:
        """Set the raw_path (and raw_bytes) for an existing document without triggering change detection."""
        with self._transaction():
            self._conn.execute(
                """
                UPDATE documents SET
                    raw_path  = ?,
                    raw_bytes = COALESCE(?, raw_bytes)
                WHERE source_type = ? AND source_id = ?
                """,
                (raw_path, raw_bytes, source_type, source_id),
            )

    def set_normalized_path(
        self,
        source_type: str,
        source_id: str,
        normalized_path: str,
        *,
        normalized_format: str = "md",
        normalizer_version: str | None = None,
        normalized_bytes: int | None = None,
    ) -> None:
        """Set the normalized_path (and related columns) for an existing document."""
        with self._transaction():
            self._conn.execute(
                """
                UPDATE documents SET
                    normalized_path    = ?,
                    normalized_format  = ?,
                    normalizer_version = COALESCE(?, normalizer_version),
                    normalized_bytes   = COALESCE(?, normalized_bytes)
                WHERE source_type = ? AND source_id = ?
                """,
                (
                    normalized_path,
                    normalized_format,
                    normalizer_version,
                    normalized_bytes,
                    source_type,
                    source_id,
                ),
            )

    def get_documents_by_normalizer_version(
        self,
        source_type: str | None,
        below_version: str,
    ) -> list[dict]:
        """Return docs whose ``normalizer_version < below_version`` (lexicographic).

        ``source_type=None`` matches any source. NULL values are treated as
        "needs normalization" and are included.
        """
        if source_type:
            rows = self._conn.execute(
                """SELECT * FROM documents
                   WHERE source_type = ?
                     AND harvest_status = 'active'
                     AND (normalizer_version IS NULL OR normalizer_version < ?)""",
                (source_type, below_version),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT * FROM documents
                   WHERE harvest_status = 'active'
                     AND (normalizer_version IS NULL OR normalizer_version < ?)""",
                (below_version,),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_metadata(self, source_type: str, source_id: str, metadata: dict) -> None:
        """Overwrite the metadata JSON for an existing document.

        No-op if the document doesn't exist.  Used to store attachment manifests
        after downloads complete without triggering change-detection logic.
        """
        with self._transaction():
            self._conn.execute(
                """
                UPDATE documents SET metadata = ?
                WHERE source_type = ? AND source_id = ?
                """,
                (json.dumps(metadata), source_type, source_id),
            )

    def mark_deleted(self, source_type: str, active_source_ids: set[str]) -> list[str]:
        """Mark documents not in active_source_ids as deleted_at_source.

        Args:
            source_type: The source to check (e.g., "notion").
            active_source_ids: All source IDs currently returned by the source.

        Returns:
            List of source_ids that were newly marked as deleted.
        """
        rows = self._conn.execute(
            "SELECT source_id FROM documents WHERE source_type = ? AND harvest_status = 'active'",
            (source_type,),
        ).fetchall()

        stored_ids = {row["source_id"] for row in rows}
        deleted_ids = stored_ids - active_source_ids

        if deleted_ids:
            placeholders = ",".join("?" * len(deleted_ids))
            with self._transaction():
                self._conn.execute(
                    f"UPDATE documents SET "
                    f"  harvest_status = 'deleted_at_source', "
                    f"  status_changed_at = ? "
                    f"WHERE source_type = ? AND source_id IN ({placeholders})",
                    (_now_iso(), source_type, *deleted_ids),
                )

        return list(deleted_ids)

    def reconcile_against_listing(
        self,
        source_type: str,
        active_source_ids: set[str],
        *,
        active_scope_ids: set[str] | None = None,
    ) -> dict[str, list[str]]:
        """Scope-aware replacement for :py:meth:`mark_deleted`.

        For every active doc not present in ``active_source_ids``:

          • If the doc has a known ``origin_scope_id`` that's NOT in the
            currently-configured ``active_scope_ids`` → mark
            ``out_of_scope``. The doc is hidden from default queries but
            stays on disk — it'll come back as ``active`` if its scope item
            is re-added.
          • If the doc has a known ``origin_scope_id`` that IS in
            ``active_scope_ids`` → genuine source-side deletion → mark
            ``deleted_at_source``.
          • If the doc's ``origin_scope_id`` is NULL (legacy row from before
            this column existed) → preserved untouched. The next successful
            harvest will tag it; until then we don't auto-archive rows we
            can't reason about.
          • ``active_scope_ids`` is ``None`` (caller doesn't know the scope)
            → fall back to the legacy behavior so tests / one-off CLI runs
            don't regress: mark everything missing as ``deleted_at_source``.

        Returns a dict with three lists of ``source_id``s:
        ``deleted`` / ``out_of_scope`` / ``preserved``.
        """
        rows = self._conn.execute(
            "SELECT source_id, origin_scope_id FROM documents "
            "WHERE source_type = ? AND harvest_status = 'active'",
            (source_type,),
        ).fetchall()

        deleted_ids: list[str] = []
        out_of_scope_ids: list[str] = []
        preserved_ids: list[str] = []

        legacy_mode = active_scope_ids is None
        scope_set = active_scope_ids or set()

        for r in rows:
            sid = r["source_id"]
            if sid in active_source_ids:
                continue
            # Legacy mode: caller didn't know the active scope (one-off CLI
            # runs, test fixtures, sources that don't track scope yet).
            # Without scope info we can't tell "user removed this scope item"
            # from "source deleted this doc", so the safe fallback per the
            # method docstring is "treat everything missing as deleted at
            # source" — preserves the pre-scope-aware contract.
            if legacy_mode:
                deleted_ids.append(sid)
                continue
            origin = r["origin_scope_id"]
            if origin is None:
                preserved_ids.append(sid)
                continue
            if origin in scope_set:
                deleted_ids.append(sid)
            else:
                out_of_scope_ids.append(sid)

        now = _now_iso()
        with self._transaction():
            if deleted_ids:
                ph = ",".join("?" * len(deleted_ids))
                self._conn.execute(
                    f"UPDATE documents SET "
                    f"  harvest_status = 'deleted_at_source', "
                    f"  status_changed_at = ? "
                    f"WHERE source_type = ? AND source_id IN ({ph})",
                    (now, source_type, *deleted_ids),
                )
            if out_of_scope_ids:
                ph = ",".join("?" * len(out_of_scope_ids))
                self._conn.execute(
                    f"UPDATE documents SET "
                    f"  harvest_status = 'out_of_scope', "
                    f"  status_changed_at = ? "
                    f"WHERE source_type = ? AND source_id IN ({ph})",
                    (now, source_type, *out_of_scope_ids),
                )

        return {
            "deleted": deleted_ids,
            "out_of_scope": out_of_scope_ids,
            "preserved": preserved_ids,
        }

    def recover_deleted(self, source_type: str | None = None) -> int:
        """Reactivate documents previously marked ``deleted_at_source``.

        Used to undo an over-eager :py:meth:`mark_deleted` (e.g. when an API
        listing returned a partial set and silently wiped good docs). The
        raw files are still on disk; we just flip the status back so the
        documents reappear in the manifest queries that drive the UI.

        Args:
            source_type: Restrict to a single source. ``None`` recovers all.

        Returns:
            Number of rows restored.
        """
        with self._transaction():
            if source_type is None:
                cur = self._conn.execute(
                    "UPDATE documents SET harvest_status = 'active' "
                    "WHERE harvest_status = 'deleted_at_source'"
                )
            else:
                cur = self._conn.execute(
                    "UPDATE documents SET harvest_status = 'active' "
                    "WHERE source_type = ? AND harvest_status = 'deleted_at_source'",
                    (source_type,),
                )
            return cur.rowcount

    def get_documents(
        self,
        source_type: str | None = None,
        status: str = "active",
    ) -> list[dict]:
        """Query documents by source type and status."""
        if source_type:
            rows = self._conn.execute(
                "SELECT * FROM documents WHERE source_type = ? AND harvest_status = ?",
                (source_type, status),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM documents WHERE harvest_status = ?",
                (status,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_origin_scope_ids(self, source_type: str) -> set[str]:
        """Return the distinct ``origin_scope_id`` values present in this source.

        Excludes ``deleted_at_source`` / ``out_of_scope`` rows so removing a
        scope item and re-adding it still flags the re-add as pending.
        """
        rows = self._conn.execute(
            "SELECT DISTINCT origin_scope_id FROM documents "
            "WHERE source_type = ? AND harvest_status = 'active' "
            "  AND origin_scope_id IS NOT NULL",
            (source_type,),
        ).fetchall()
        return {r["origin_scope_id"] for r in rows}

    def get_last_scope_snapshot(self, source_type: str) -> list[str] | None:
        """Return the scope ids recorded at the end of the most recent
        successful non-scoped harvest run for this source.

        ``None`` means "no successful run yet" — the Connections card uses
        that to flag a fresh connection (all configured scope items count
        as pending).
        """
        row = self._conn.execute(
            "SELECT last_scope_snapshot FROM source_state WHERE source_type = ?",
            (source_type,),
        ).fetchone()
        if row is None or row["last_scope_snapshot"] is None:
            return None
        try:
            return json.loads(row["last_scope_snapshot"])
        except (json.JSONDecodeError, TypeError):
            return None

    def set_last_scope_snapshot(
        self, source_type: str, scope_ids: list[str]
    ) -> None:
        """Persist the YAML scope at the end of a successful harvest run.

        Called by the API orchestrator's ``_run_one`` so the next call to
        ``/api/connections`` can diff current YAML scope against this
        snapshot to compute a stable "items added since last harvest" count.
        """
        with self._transaction():
            self._conn.execute(
                """
                INSERT INTO source_state (source_type, last_scope_snapshot, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source_type) DO UPDATE SET
                    last_scope_snapshot = excluded.last_scope_snapshot,
                    updated_at          = excluded.updated_at
                """,
                (source_type, json.dumps(list(scope_ids)), _now_iso()),
            )

    def get_documents_by_converter_version(
        self,
        source_type: str,
        below_version: str,
    ) -> list[dict]:
        """Return documents processed by a converter_version < below_version.

        Useful for re-processing when the pipeline improves.  Uses simple
        lexicographic comparison which works for semver strings (0.1.0, 0.2.0).
        """
        rows = self._conn.execute(
            """SELECT * FROM documents
               WHERE source_type = ?
                 AND converter_version IS NOT NULL
                 AND converter_version < ?""",
            (source_type, below_version),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Harvest run operations ─────────────────────────────────────

    def start_run(
        self,
        source_type: str | None = None,
        mode: str = "scheduled",
    ) -> str:
        """Create a harvest_runs entry and return its run_id."""
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        with self._transaction():
            self._conn.execute(
                """
                INSERT INTO harvest_runs (id, started_at, source_type, mode)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, _now_iso(), source_type, mode),
            )
        return run_id

    def complete_run(self, run_id: str, stats: dict) -> None:
        """Finalise a harvest run with completion stats.

        Stats dict keys (all optional, default to 0):
            found, harvested, skipped, failed, errors (list), warnings (dict)
        """
        with self._transaction():
            self._conn.execute(
                """
                UPDATE harvest_runs SET
                    completed_at   = ?,
                    docs_found     = ?,
                    docs_harvested = ?,
                    docs_skipped   = ?,
                    docs_failed    = ?,
                    errors         = ?,
                    warnings       = ?
                WHERE id = ?
                """,
                (
                    _now_iso(),
                    stats.get("found", 0),
                    stats.get("harvested", 0),
                    stats.get("skipped", 0),
                    stats.get("failed", 0),
                    json.dumps(stats.get("errors", [])),
                    json.dumps(stats.get("warnings", {})),
                    run_id,
                ),
            )

    def get_last_harvest_time(self, source_type: str) -> datetime | None:
        """Return the harvested_at time of the most recent completed run for a source.

        This is used as the `since` parameter for the next list_documents() call.
        Returns None if no previous run exists (triggers a full backfill).
        """
        row = self._conn.execute(
            """
            SELECT completed_at FROM harvest_runs
            WHERE source_type = ? AND completed_at IS NOT NULL
            ORDER BY completed_at DESC
            LIMIT 1
            """,
            (source_type,),
        ).fetchone()
        return _parse_dt(row["completed_at"]) if row else None

    def get_last_harvest_time_any(self) -> datetime | None:
        """Return the completed_at of the most recent completed run across all sources.

        Used by /api/changes to answer "when did we last check the sources?".
        Returns None when no run has ever completed.
        """
        row = self._conn.execute(
            "SELECT MAX(completed_at) AS completed_at FROM harvest_runs WHERE completed_at IS NOT NULL"
        ).fetchone()
        value = row["completed_at"] if row else None
        return _parse_dt(value) if value else None

    def get_run(self, run_id: str) -> dict | None:
        """Fetch a harvest run by ID."""
        row = self._conn.execute(
            "SELECT * FROM harvest_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_runs(self, *, limit: int = 20) -> list[dict]:
        """Return the most recent harvest runs (any source), newest first.

        Powers ``/api/harvest/history``. The route maps these dicts into the
        ``HarvestRun`` shape the frontend expects — see ``routes_harvest.history``.
        """
        rows = self._conn.execute(
            """
            SELECT id, started_at, completed_at, source_type, mode,
                   docs_found, docs_harvested, docs_skipped, docs_failed,
                   errors, warnings
            FROM harvest_runs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        """Return high-level manifest statistics."""
        total = self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        by_source = self._conn.execute(
            "SELECT source_type, harvest_status, COUNT(*) as n "
            "FROM documents GROUP BY source_type, harvest_status"
        ).fetchall()
        runs = self._conn.execute("SELECT COUNT(*) FROM harvest_runs").fetchone()[0]
        return {
            "total_documents": total,
            "total_runs": runs,
            "by_source": [dict(r) for r in by_source],
        }
