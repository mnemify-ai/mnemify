"""``<data_dir>/workspace.db`` — user-authored state for region workspaces.

Everything the *user* makes while working inside a region lives here, kept
apart from ``terrain.db`` on purpose: that file is a compile cache that a
harvest reset or purge may wipe, while memory items and conversations must
survive every recompile. Only the full ``POST /api/reset`` (type-to-confirm)
removes this file.

Tables
------
``region_anchors``   One row per region the user has touched. ``key`` is the
                     stable internal id every other table references; only
                     ``region_id`` is remapped after a compile (region ids are
                     content hashes — see ``region_reconcile.py``).
``memory_items``     Findings the user chose to keep (promoted chat answers).
``threads`` /        Ask conversations, persisted by ``POST /api/ask`` when
``thread_messages``  the client sends a ``thread_id``.
``action_item_status``  Per-signal review status (``unverified`` /
                     ``confirmed`` / ``dismissed``), keyed by the content-hashed
                     signal id, which survives recompiles.
``region_visits``    Last-visit stamp per region ("since your last visit").
``overview_briefs``  LLM-refreshed brief per region, superseded by a compile.
``reconcile_log``    Audit of each re-attachment pass.

Same ``PRAGMA user_version`` protection as the other two stores: a file
written by a newer Mnemify refuses to open.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

ACTION_ITEM_STATUSES = ("unverified", "confirmed", "dismissed")
MEMORY_KINDS = ("answer", "selection")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _loads(raw: object, default):
    if not isinstance(raw, str):
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


class WorkspaceStore:
    SCHEMA_VERSION = 1

    _DDL = (
        """
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS region_anchors (
            key                   TEXT PRIMARY KEY,
            region_id             TEXT,
            region_name           TEXT NOT NULL,
            level                 INTEGER,
            member_note_ids       TEXT NOT NULL DEFAULT '[]',
            status                TEXT NOT NULL DEFAULT 'attached',
            region_id_history     TEXT NOT NULL DEFAULT '[]',
            snapshot_generated_at TEXT,
            created_at            TEXT NOT NULL,
            updated_at            TEXT NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_region_anchors_region_id
            ON region_anchors (region_id) WHERE region_id IS NOT NULL
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_items (
            id              TEXT PRIMARY KEY,
            region_key      TEXT NOT NULL REFERENCES region_anchors(key) ON DELETE CASCADE,
            title           TEXT NOT NULL,
            body            TEXT NOT NULL,
            kind            TEXT NOT NULL DEFAULT 'answer',
            citations       TEXT NOT NULL DEFAULT '[]',
            source_note_ids TEXT NOT NULL DEFAULT '[]',
            origin          TEXT NOT NULL DEFAULT '{}',
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_memory_region ON memory_items (region_key, created_at)",
        """
        CREATE TABLE IF NOT EXISTS threads (
            id          TEXT PRIMARY KEY,
            region_key  TEXT REFERENCES region_anchors(key) ON DELETE SET NULL,
            title       TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_threads_region ON threads (region_key, updated_at)",
        """
        CREATE TABLE IF NOT EXISTS thread_messages (
            id          TEXT PRIMARY KEY,
            thread_id   TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
            seq         INTEGER NOT NULL,
            role        TEXT NOT NULL,
            text        TEXT NOT NULL,
            payload     TEXT NOT NULL DEFAULT '{}',
            created_at  TEXT NOT NULL,
            UNIQUE (thread_id, seq)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS action_item_status (
            signal_id  TEXT PRIMARY KEY,
            status     TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS region_visits (
            region_key      TEXT PRIMARY KEY REFERENCES region_anchors(key) ON DELETE CASCADE,
            last_visited_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS overview_briefs (
            region_key           TEXT PRIMARY KEY REFERENCES region_anchors(key) ON DELETE CASCADE,
            text                 TEXT NOT NULL,
            provider             TEXT NOT NULL,
            model                TEXT NOT NULL,
            terrain_generated_at TEXT NOT NULL,
            created_at           TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reconcile_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_at  TEXT NOT NULL,
            ran_at        TEXT NOT NULL,
            report        TEXT NOT NULL
        )
        """,
    )

    @staticmethod
    def default_path() -> Path:
        from src import paths

        return paths.data_dir() / "workspace.db"

    @classmethod
    def open_if_exists(cls, db_path: str | Path | None = None) -> "WorkspaceStore | None":
        """For read paths: never create the file (a GET must not resurrect a
        wiped ``.mnemify/``)."""
        p = Path(db_path) if db_path is not None else cls.default_path()
        if not p.is_file():
            return None
        return cls(p)

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = self.default_path()
        self.db_path = Path(db_path)
        if self.db_path != Path(":memory:"):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._check_schema_version()
        self._init_schema()

    def _check_schema_version(self) -> None:
        found = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if found > self.SCHEMA_VERSION:
            self._conn.close()
            raise RuntimeError(
                f"{self.db_path} was written by a newer Mnemify "
                f"(schema v{found}; this build understands v{self.SCHEMA_VERSION}). "
                f"Update the code and re-run setup."
            )

    def _init_schema(self) -> None:
        with self._transaction():
            for ddl in self._DDL:
                self._conn.execute(ddl)
            self._conn.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "WorkspaceStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── meta ──────────────────────────────────────────────────────────

    def meta_get(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def meta_set(self, key: str, value: str) -> None:
        with self._transaction():
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ── anchors ───────────────────────────────────────────────────────

    @staticmethod
    def _anchor_row(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["member_note_ids"] = _loads(d.get("member_note_ids"), [])
        d["region_id_history"] = _loads(d.get("region_id_history"), [])
        return d

    def anchor_by_region_id(self, region_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM region_anchors WHERE region_id = ?", (region_id,)
        ).fetchone()
        return self._anchor_row(row) if row else None

    def anchor_by_key(self, key: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM region_anchors WHERE key = ?", (key,)).fetchone()
        return self._anchor_row(row) if row else None

    def anchors_all(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM region_anchors ORDER BY created_at").fetchall()
        return [self._anchor_row(r) for r in rows]

    def anchor_for_history_id(self, old_region_id: str) -> dict | None:
        """The anchor whose ``region_id_history`` contains ``old_region_id``
        (an old URL after a recompile)."""
        for a in self.anchors_all():
            if old_region_id in a["region_id_history"]:
                return a
        return None

    def get_or_create_anchor(
        self,
        region_id: str,
        *,
        name: str,
        level: int | None,
        note_ids: set[str] | list[str],
        generated_at: str | None,
    ) -> dict:
        existing = self.anchor_by_region_id(region_id)
        if existing:
            return existing
        key = _new_id("rk")
        now = _now()
        with self._transaction():
            self._conn.execute(
                "INSERT INTO region_anchors (key, region_id, region_name, level, "
                "member_note_ids, status, region_id_history, snapshot_generated_at, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'attached', '[]', ?, ?, ?)",
                (key, region_id, name, level, json.dumps(sorted(note_ids)), generated_at, now, now),
            )
        return self.anchor_by_key(key)  # type: ignore[return-value]

    def remap_anchor(
        self,
        key: str,
        *,
        region_id: str,
        name: str,
        level: int | None,
        note_ids: set[str] | list[str],
        generated_at: str | None,
    ) -> None:
        current = self.anchor_by_key(key)
        if current is None:
            return
        history = list(current["region_id_history"])
        old = current.get("region_id")
        if old and old != region_id and old not in history:
            history.append(old)
        with self._transaction():
            self._conn.execute(
                "UPDATE region_anchors SET region_id = ?, region_name = ?, level = ?, "
                "member_note_ids = ?, status = 'attached', region_id_history = ?, "
                "snapshot_generated_at = ?, updated_at = ? WHERE key = ?",
                (
                    region_id, name, level, json.dumps(sorted(note_ids)),
                    json.dumps(history), generated_at, _now(), key,
                ),
            )

    def orphan_anchor(self, key: str) -> None:
        current = self.anchor_by_key(key)
        if current is None:
            return
        history = list(current["region_id_history"])
        old = current.get("region_id")
        if old and old not in history:
            history.append(old)
        with self._transaction():
            self._conn.execute(
                "UPDATE region_anchors SET region_id = NULL, status = 'orphaned', "
                "region_id_history = ?, updated_at = ? WHERE key = ?",
                (json.dumps(history), _now(), key),
            )

    def anchor_counts(self, keys: list[str]) -> dict[str, dict[str, int]]:
        """``{key: {memory, threads}}`` for the given anchor keys."""
        out = {k: {"memory": 0, "threads": 0} for k in keys}
        if not keys:
            return out
        marks = ",".join("?" * len(keys))
        for row in self._conn.execute(
            f"SELECT region_key, COUNT(*) AS n FROM memory_items "
            f"WHERE region_key IN ({marks}) GROUP BY region_key", keys
        ):
            out[row["region_key"]]["memory"] = row["n"]
        for row in self._conn.execute(
            f"SELECT region_key, COUNT(*) AS n FROM threads "
            f"WHERE region_key IN ({marks}) GROUP BY region_key", keys
        ):
            out[row["region_key"]]["threads"] = row["n"]
        return out

    # ── memory ────────────────────────────────────────────────────────

    @staticmethod
    def _memory_row(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["citations"] = _loads(d.get("citations"), [])
        d["source_note_ids"] = _loads(d.get("source_note_ids"), [])
        d["origin"] = _loads(d.get("origin"), {})
        return d

    def list_memory(self, keys: list[str], *, limit: int | None = None) -> list[dict]:
        if not keys:
            return []
        marks = ",".join("?" * len(keys))
        sql = (
            f"SELECT * FROM memory_items WHERE region_key IN ({marks}) "
            "ORDER BY created_at DESC"
        )
        params: list = list(keys)
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [self._memory_row(r) for r in self._conn.execute(sql, params)]

    def get_memory(self, item_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM memory_items WHERE id = ?", (item_id,)).fetchone()
        return self._memory_row(row) if row else None

    def create_memory(
        self,
        region_key: str,
        *,
        title: str,
        body: str,
        kind: str = "answer",
        citations: list | None = None,
        source_note_ids: list[str] | None = None,
        origin: dict | None = None,
    ) -> dict:
        if kind not in MEMORY_KINDS:
            raise ValueError(f"unknown memory kind {kind!r}")
        item_id = _new_id("mem")
        now = _now()
        with self._transaction():
            self._conn.execute(
                "INSERT INTO memory_items (id, region_key, title, body, kind, citations, "
                "source_note_ids, origin, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_id, region_key, title, body, kind,
                    json.dumps(citations or []), json.dumps(source_note_ids or []),
                    json.dumps(origin or {}), now, now,
                ),
            )
        return self.get_memory(item_id)  # type: ignore[return-value]

    def update_memory(
        self,
        item_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        region_key: str | None = None,
    ) -> dict | None:
        current = self.get_memory(item_id)
        if current is None:
            return None
        with self._transaction():
            self._conn.execute(
                "UPDATE memory_items SET title = ?, body = ?, region_key = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    title if title is not None else current["title"],
                    body if body is not None else current["body"],
                    region_key if region_key is not None else current["region_key"],
                    _now(), item_id,
                ),
            )
        return self.get_memory(item_id)

    def delete_memory(self, item_id: str) -> bool:
        with self._transaction():
            cur = self._conn.execute("DELETE FROM memory_items WHERE id = ?", (item_id,))
        return cur.rowcount > 0

    # ── threads ───────────────────────────────────────────────────────

    def get_thread(self, thread_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        return dict(row) if row else None

    def ensure_thread(
        self, thread_id: str | None, *, region_key: str | None, title: str
    ) -> dict:
        """Return the thread, creating it when missing. A client-supplied id
        is honoured so the browser's local thread and the stored one agree."""
        if thread_id:
            existing = self.get_thread(thread_id)
            if existing:
                return existing
        tid = thread_id or _new_id("th")
        now = _now()
        with self._transaction():
            self._conn.execute(
                "INSERT INTO threads (id, region_key, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (tid, region_key, title[:120] or "New thread", now, now),
            )
        return self.get_thread(tid)  # type: ignore[return-value]

    def set_thread_region(self, thread_id: str, region_key: str | None) -> None:
        with self._transaction():
            self._conn.execute(
                "UPDATE threads SET region_key = ?, updated_at = ? WHERE id = ?",
                (region_key, _now(), thread_id),
            )

    def append_messages(self, thread_id: str, messages: list[dict]) -> None:
        """``messages``: ``[{id?, role, text, payload?, created_at?}]``. Appends
        in order after the thread's current last ``seq``; a message id that
        already exists is skipped (idempotent re-imports)."""
        if not messages:
            return
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), -1) AS s FROM thread_messages WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        seq = int(row["s"]) + 1
        now = _now()
        with self._transaction():
            for m in messages:
                mid = m.get("id") or _new_id("msg")
                exists = self._conn.execute(
                    "SELECT 1 FROM thread_messages WHERE id = ?", (mid,)
                ).fetchone()
                if exists:
                    continue
                self._conn.execute(
                    "INSERT INTO thread_messages (id, thread_id, seq, role, text, payload, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        mid, thread_id, seq, m.get("role") or "user", m.get("text") or "",
                        json.dumps(m.get("payload") or {}), m.get("created_at") or now,
                    ),
                )
                seq += 1
            first_user = next((m for m in messages if m.get("role") == "user"), None)
            thread = self.get_thread(thread_id)
            title = thread["title"] if thread else "New thread"
            if thread and thread["title"] in ("", "New thread") and first_user:
                title = (first_user.get("text") or "").strip()[:64] or title
            self._conn.execute(
                "UPDATE threads SET updated_at = ?, title = ? WHERE id = ?",
                (now, title, thread_id),
            )

    def thread_messages(self, thread_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM thread_messages WHERE thread_id = ? ORDER BY seq", (thread_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = _loads(d.get("payload"), {})
            out.append(d)
        return out

    def list_threads(self, keys: list[str] | None) -> list[dict]:
        """Threads for the given anchor keys, or every thread when ``keys`` is
        ``None``. Newest-updated first, with ``message_count``."""
        base = (
            "SELECT t.*, (SELECT COUNT(*) FROM thread_messages m WHERE m.thread_id = t.id) "
            "AS message_count FROM threads t"
        )
        if keys is None:
            rows = self._conn.execute(base + " ORDER BY t.updated_at DESC").fetchall()
        else:
            if not keys:
                return []
            marks = ",".join("?" * len(keys))
            rows = self._conn.execute(
                base + f" WHERE t.region_key IN ({marks}) ORDER BY t.updated_at DESC", keys
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_thread(self, thread_id: str) -> bool:
        with self._transaction():
            cur = self._conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
        return cur.rowcount > 0

    def import_threads(self, threads: list[dict]) -> tuple[int, int]:
        """One-time import of the browser's localStorage threads. Returns
        ``(imported, skipped)``; an existing thread id is skipped whole."""
        imported = skipped = 0
        for t in threads:
            tid = t.get("id")
            if not isinstance(tid, str) or not tid:
                skipped += 1
                continue
            if self.get_thread(tid):
                skipped += 1
                continue
            created = _ms_to_iso(t.get("createdAt"))
            updated = _ms_to_iso(t.get("updatedAt"))
            with self._transaction():
                self._conn.execute(
                    "INSERT INTO threads (id, region_key, title, created_at, updated_at) "
                    "VALUES (?, NULL, ?, ?, ?)",
                    (tid, (t.get("title") or "New thread")[:120], created, updated),
                )
            msgs = []
            for m in t.get("messages") or []:
                if not isinstance(m, dict):
                    continue
                payload = {k: v for k, v in m.items() if k not in ("id", "role", "text")}
                msgs.append({
                    "id": m.get("id"), "role": m.get("role"), "text": m.get("text") or "",
                    "payload": payload, "created_at": created,
                })
            self.append_messages(tid, msgs)
            # Keep the client's own stamps rather than "now".
            with self._transaction():
                self._conn.execute(
                    "UPDATE threads SET updated_at = ?, title = ? WHERE id = ?",
                    (updated, (t.get("title") or "New thread")[:120], tid),
                )
            imported += 1
        return imported, skipped

    # ── action-item statuses ──────────────────────────────────────────

    def set_status(self, signal_id: str, status: str) -> dict:
        if status not in ACTION_ITEM_STATUSES:
            raise ValueError(f"unknown status {status!r}")
        now = _now()
        with self._transaction():
            self._conn.execute(
                "INSERT INTO action_item_status (signal_id, status, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(signal_id) DO UPDATE SET status = excluded.status, "
                "updated_at = excluded.updated_at",
                (signal_id, status, now),
            )
        return {"signal_id": signal_id, "status": status, "updated_at": now}

    def statuses(self, signal_ids: list[str] | None = None) -> dict[str, str]:
        if signal_ids is None:
            rows = self._conn.execute("SELECT signal_id, status FROM action_item_status").fetchall()
        else:
            if not signal_ids:
                return {}
            marks = ",".join("?" * len(signal_ids))
            rows = self._conn.execute(
                f"SELECT signal_id, status FROM action_item_status WHERE signal_id IN ({marks})",
                signal_ids,
            ).fetchall()
        return {r["signal_id"]: r["status"] for r in rows}

    def import_dismissals(self, signal_ids: list[str]) -> tuple[int, int]:
        """Import legacy localStorage dismissals; never overwrite an existing
        row (a ``confirmed`` must not be downgraded)."""
        imported = skipped = 0
        now = _now()
        with self._transaction():
            for sid in signal_ids:
                if not isinstance(sid, str) or not sid:
                    skipped += 1
                    continue
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO action_item_status (signal_id, status, updated_at) "
                    "VALUES (?, 'dismissed', ?)",
                    (sid, now),
                )
                if cur.rowcount:
                    imported += 1
                else:
                    skipped += 1
        return imported, skipped

    # ── visits ────────────────────────────────────────────────────────

    def last_visit(self, region_key: str) -> str | None:
        row = self._conn.execute(
            "SELECT last_visited_at FROM region_visits WHERE region_key = ?", (region_key,)
        ).fetchone()
        return row["last_visited_at"] if row else None

    def touch_visit(self, region_key: str) -> tuple[str | None, str]:
        previous = self.last_visit(region_key)
        now = _now()
        with self._transaction():
            self._conn.execute(
                "INSERT INTO region_visits (region_key, last_visited_at) VALUES (?, ?) "
                "ON CONFLICT(region_key) DO UPDATE SET last_visited_at = excluded.last_visited_at",
                (region_key, now),
            )
        return previous, now

    # ── briefs ────────────────────────────────────────────────────────

    def get_brief(self, region_key: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM overview_briefs WHERE region_key = ?", (region_key,)
        ).fetchone()
        return dict(row) if row else None

    def put_brief(
        self, region_key: str, *, text: str, provider: str, model: str, terrain_generated_at: str
    ) -> dict:
        now = _now()
        with self._transaction():
            self._conn.execute(
                "INSERT INTO overview_briefs (region_key, text, provider, model, "
                "terrain_generated_at, created_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(region_key) DO UPDATE SET text = excluded.text, "
                "provider = excluded.provider, model = excluded.model, "
                "terrain_generated_at = excluded.terrain_generated_at, "
                "created_at = excluded.created_at",
                (region_key, text, provider, model, terrain_generated_at, now),
            )
        return self.get_brief(region_key)  # type: ignore[return-value]

    # ── reconcile log ─────────────────────────────────────────────────

    def log_reconcile(self, generated_at: str, report: dict) -> None:
        with self._transaction():
            self._conn.execute(
                "INSERT INTO reconcile_log (generated_at, ran_at, report) VALUES (?, ?, ?)",
                (generated_at, _now(), json.dumps(report)),
            )

    def reconcile_log(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM reconcile_log ORDER BY id").fetchall()
        return [{**dict(r), "report": _loads(r["report"], {})} for r in rows]


def _ms_to_iso(value: object) -> str:
    if isinstance(value, (int, float)) and value > 0:
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    return _now()
