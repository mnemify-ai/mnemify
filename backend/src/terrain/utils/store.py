from __future__ import annotations

import json
import sqlite3
import uuid

import numpy as np
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from src.terrain.utils.models import ChunkFeatures, TerrainChunk


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



class TerrainStore:
    _DDL = [
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            doc_title TEXT NOT NULL,
            source_url TEXT,
            source_parent_id TEXT,
            source_parent_title TEXT,
            source_ancestor_ids TEXT NOT NULL,
            source_breadcrumb_titles TEXT NOT NULL,
            heading_path TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            content TEXT NOT NULL,
            region_assignments TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS chunk_features (
            content_hash TEXT PRIMARY KEY,
            features TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS embeddings (
            embedding_hash TEXT PRIMARY KEY,
            model TEXT NOT NULL,
            vector TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cluster_tree_nodes (
            run_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            parent_id TEXT,
            depth INTEGER NOT NULL,
            chunk_ids TEXT NOT NULL,
            PRIMARY KEY (run_id, node_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cluster_names (
            fingerprint TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            summary TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS layout_seeds (
            node_id TEXT PRIMARY KEY,
            x REAL NOT NULL,
            z REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS compiled_notes (
            cache_key TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            embedding TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS compiled_note_members (
            cache_key TEXT NOT NULL,
            kind TEXT NOT NULL,
            member_hash TEXT NOT NULL,
            PRIMARY KEY (cache_key, member_hash)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_compiled_note_members_lookup
            ON compiled_note_members (kind, member_hash)
        """,
        """
        CREATE TABLE IF NOT EXISTS terrain_runs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            params TEXT NOT NULL,
            counts TEXT NOT NULL,
            error TEXT
        )
        """,
        # Raw graph-node embeddings, kept out of terrain.json (they were ~98%
        # of its size). Only the raw vector is stored — context embeddings are
        # a deterministic function of raw vectors + edges and are recomputed
        # at load time (graph_embed.apply_context_embeddings).
        """
        CREATE TABLE IF NOT EXISTS graph_node_vectors (
            node_id TEXT PRIMARY KEY,
            model TEXT,
            vector BLOB NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        # Region-merger decisions per compile run (audit + weak labels for
        # threshold calibration — see scripts/threshold_eval.py). Labels are
        # the heuristic names the LLM judge saw, not the final region names.
        """
        CREATE TABLE IF NOT EXISTS merger_verdicts (
            run_id TEXT NOT NULL,
            a_id TEXT NOT NULL,
            b_id TEXT NOT NULL,
            similarity REAL NOT NULL,
            decision TEXT NOT NULL,
            parent TEXT,
            reason TEXT NOT NULL DEFAULT '',
            a_label TEXT NOT NULL DEFAULT '',
            b_label TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, a_id, b_id)
        )
        """,
    ]

    def __init__(self, db_path: str | Path = ".mnemify/terrain.db"):
        self.db_path = Path(db_path)
        if self.db_path != Path(":memory:"):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._transaction():
            for ddl in self._DDL:
                self._conn.execute(ddl)
            self._ensure_column("chunks", "region_assignments", "TEXT NOT NULL DEFAULT '[]'")
            # Stamped at the end of enrich; lets /api/ask join chunk → vector
            # directly instead of re-deriving the embedding hash (which isn't
            # reproducible from persisted rows — wikilinks/frontmatter aren't
            # stored). NULL on rows from compiles that predate the column.
            self._ensure_column("chunks", "embedding_hash", "TEXT")
            # Overlap-tolerant note reuse (see ``find_similar_compiled_note``):
            # ``member_count`` is the size of the member set the note was
            # synthesized from; ``drift`` counts how many times the note has
            # been carried forward onto a near-identical member set without
            # re-synthesis. Rows from older compiles have NULL/0 and simply
            # never match the fuzzy path (no member rows).
            self._ensure_column("compiled_notes", "member_count", "INTEGER")
            self._ensure_column("compiled_notes", "drift", "INTEGER NOT NULL DEFAULT 0")
            # The cache_key of the row the LLM actually produced; carried-forward
            # copies share it so ``drift`` can be bumped across the whole family.
            self._ensure_column("compiled_notes", "origin_key", "TEXT")

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        columns = {
            row["name"]
            for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

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

    def start_run(self, params: dict | None = None) -> str:
        run_id = f"terrain_{uuid.uuid4().hex[:12]}"
        with self._transaction():
            self._conn.execute(
                """
                INSERT INTO terrain_runs (id, status, started_at, params, counts)
                VALUES (?, 'running', ?, ?, '{}')
                """,
                (run_id, _now_iso(), json.dumps(params or {})),
            )
        return run_id

    def complete_run(self, run_id: str, counts: dict) -> None:
        with self._transaction():
            self._conn.execute(
                """
                UPDATE terrain_runs
                SET status='completed', completed_at=?, counts=?
                WHERE id=?
                """,
                (_now_iso(), json.dumps(counts), run_id),
            )

    def fail_run(self, run_id: str, error: str, counts: dict | None = None) -> None:
        """Mark a run failed. ``counts`` (optional) records what the run did
        before it died — e.g. LLM usage so far — so a resumed run's report can
        still account for the spend."""
        with self._transaction():
            if counts is not None:
                self._conn.execute(
                    """
                    UPDATE terrain_runs
                    SET status='failed', completed_at=?, error=?, counts=?
                    WHERE id=?
                    """,
                    (_now_iso(), error, json.dumps(counts), run_id),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE terrain_runs
                    SET status='failed', completed_at=?, error=?
                    WHERE id=?
                    """,
                    (_now_iso(), error, run_id),
                )

    def fail_orphaned_runs(self) -> int:
        """Mark any still-'running' run as failed — called on app startup.

        A 'running' row after a restart means the process died mid-build (the
        compile runs in an asyncio worker thread that dies with the process;
        there's no resume). The chunk/feature/embedding caches survive, so a
        re-run is fast. Returns the number of rows fixed.
        """
        with self._transaction():
            cur = self._conn.execute(
                """
                UPDATE terrain_runs
                SET status='failed', completed_at=?, error='server restarted'
                WHERE status='running'
                """,
                (_now_iso(),),
            )
            return cur.rowcount

    def get_last_compile_time(self) -> str | None:
        """ISO timestamp of the most recent successfully completed run, or None."""
        row = self._conn.execute(
            """
            SELECT completed_at FROM terrain_runs
            WHERE status='completed' AND completed_at IS NOT NULL
            ORDER BY completed_at DESC
            LIMIT 1
            """
        ).fetchone()
        return row["completed_at"] if row else None

    def recent_runs(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT * FROM terrain_runs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def replace_graph_node_vectors(
        self, vectors: dict[str, list[float]], model: str | None = None
    ) -> None:
        """Full replace (DELETE + insert) so node ids from a prior compile
        never linger and get hydrated onto the wrong generation's graph."""
        now = _now_iso()
        with self._transaction():
            self._conn.execute("DELETE FROM graph_node_vectors")
            self._conn.executemany(
                """
                INSERT INTO graph_node_vectors (node_id, model, vector, updated_at)
                VALUES (?,?,?,?)
                """,
                [
                    (node_id, model, np.asarray(vec, dtype=np.float32).tobytes(), now)
                    for node_id, vec in vectors.items()
                ],
            )

    def load_graph_node_vectors(self) -> dict[str, list[float]]:
        rows = self._conn.execute(
            "SELECT node_id, vector FROM graph_node_vectors"
        ).fetchall()
        return {
            row["node_id"]: np.frombuffer(row["vector"], dtype=np.float32)
            .astype(float)
            .tolist()
            for row in rows
        }

    def upsert_chunks(self, chunks: list[TerrainChunk]) -> None:
        with self._transaction():
            for c in chunks:
                self._conn.execute(
                    """
                    INSERT INTO chunks (
                        id, doc_id, source_type, source_id, doc_title, source_url,
                        source_parent_id, source_parent_title, source_ancestor_ids,
                        source_breadcrumb_titles, heading_path, content_hash, content,
                        region_assignments, updated_at
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        content_hash=excluded.content_hash,
                        content=excluded.content,
                        heading_path=excluded.heading_path,
                        region_assignments=excluded.region_assignments,
                        updated_at=excluded.updated_at
                    """,
                    (
                        c.id, c.doc_id, c.source_type, c.source_id, c.doc_title,
                        c.source_url, c.source_parent_id, c.source_parent_title,
                        json.dumps(c.source_ancestor_ids),
                        json.dumps(c.source_breadcrumb_titles),
                        json.dumps(c.heading_path), c.content_hash, c.content,
                        json.dumps(c.region_assignments),
                        _now_iso(),
                    ),
                )

    def delete_chunks_not_in(self, keep_ids: list[str]) -> int:
        """Drop chunk rows that are not part of the current compile.

        Chunk ids are content-derived, so a re-chunked or re-embedded corpus
        leaves orphans behind (e.g. rows embedded with a different model on an
        earlier run). They are never read by the map, but they confuse any
        analysis that joins ``chunks`` to ``embeddings``. Returns rows removed.
        """
        keep = set(keep_ids)
        rows = self._conn.execute("SELECT id FROM chunks").fetchall()
        stale = [r["id"] for r in rows if r["id"] not in keep]
        if not stale:
            return 0
        with self._transaction():
            for i in range(0, len(stale), 500):
                batch = stale[i:i + 500]
                self._conn.execute(
                    f"DELETE FROM chunks WHERE id IN ({','.join('?' * len(batch))})", batch
                )
        return len(stale)

    def get_chunks_by_ids(self, ids: list[str]) -> list[dict]:
        """Fetch raw chunk rows for the given ids (read path for /api/ask
        chunk expansion). Returns dicts with id, doc_id, doc_title,
        heading_path (decoded list), content, source_url, and updated_at
        (compile/ingest timestamp — used as the citation popover's "date"
        signal); missing ids are skipped."""
        out: list[dict] = []
        for start in range(0, len(ids), 500):
            batch = ids[start : start + 500]
            placeholders = ",".join("?" * len(batch))
            rows = self._conn.execute(
                f"""
                SELECT id, doc_id, doc_title, heading_path, content, source_url, updated_at
                FROM chunks WHERE id IN ({placeholders})
                """,
                batch,
            ).fetchall()
            for row in rows:
                out.append(
                    {
                        "id": row["id"],
                        "doc_id": row["doc_id"],
                        "doc_title": row["doc_title"],
                        "heading_path": json.loads(row["heading_path"] or "[]"),
                        "content": row["content"],
                        "source_url": row["source_url"],
                        "updated_at": row["updated_at"],
                    }
                )
        # Preserve the caller's requested order.
        by_id = {c["id"]: c for c in out}
        return [by_id[i] for i in ids if i in by_id]

    def get_doc_chunk_index(self) -> dict[str, list[str]]:
        """Map every doc_id to its chunk ids (ids only — cheap)."""
        index: dict[str, list[str]] = {}
        for row in self._conn.execute("SELECT id, doc_id FROM chunks ORDER BY id"):
            index.setdefault(row["doc_id"], []).append(row["id"])
        return index

    def get_features(self, content_hash: str) -> ChunkFeatures | None:
        row = self._conn.execute(
            "SELECT features FROM chunk_features WHERE content_hash=?",
            (content_hash,),
        ).fetchone()
        return ChunkFeatures.model_validate_json(row["features"]) if row else None

    def save_features(self, content_hash: str, features: ChunkFeatures) -> None:
        with self._transaction():
            self._conn.execute(
                """
                INSERT INTO chunk_features (content_hash, features, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(content_hash) DO UPDATE SET
                    features=excluded.features,
                    updated_at=excluded.updated_at
                """,
                (content_hash, features.model_dump_json(), _now_iso()),
            )

    def save_chunk_embedding_hashes(self, mapping: dict[str, str]) -> None:
        """Stamp ``chunks.embedding_hash`` for the given chunk ids (batch)."""
        if not mapping:
            return
        with self._transaction():
            self._conn.executemany(
                "UPDATE chunks SET embedding_hash=? WHERE id=?",
                [(ehash, chunk_id) for chunk_id, ehash in mapping.items()],
            )

    def get_chunk_vectors(self) -> list[dict]:
        """Every chunk with a stamped embedding hash, joined to its vector.

        Read path for /api/ask chunk-level semantic search. Rows compiled
        before ``embedding_hash`` stamping landed have NULL and are skipped —
        chunk search simply covers less until the next compile."""
        rows = self._conn.execute(
            """
            SELECT c.id, c.doc_id, e.vector
            FROM chunks c JOIN embeddings e ON e.embedding_hash = c.embedding_hash
            WHERE c.embedding_hash IS NOT NULL
            """
        ).fetchall()
        return [
            {
                "id": row["id"],
                "doc_id": row["doc_id"],
                "vector": json.loads(row["vector"]),
            }
            for row in rows
        ]

    def get_embedding(self, embedding_hash: str) -> list[float] | None:
        row = self._conn.execute(
            "SELECT vector FROM embeddings WHERE embedding_hash=?",
            (embedding_hash,),
        ).fetchone()
        return json.loads(row["vector"]) if row else None

    def save_embedding(self, embedding_hash: str, model: str, vector: list[float]) -> None:
        with self._transaction():
            self._conn.execute(
                """
                INSERT INTO embeddings (embedding_hash, model, vector, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(embedding_hash) DO UPDATE SET
                    model=excluded.model,
                    vector=excluded.vector,
                    updated_at=excluded.updated_at
                """,
                (embedding_hash, model, json.dumps(vector), _now_iso()),
            )

    def save_assignments(self, run_id: str, assignments: list) -> None:
        with self._transaction():
            def save_node(node, parent_id: str | None, depth: int) -> None:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO cluster_tree_nodes
                        (run_id, node_id, parent_id, depth, chunk_ids)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        node.id,
                        parent_id,
                        depth,
                        json.dumps(node.chunk_ids),
                    ),
                )
                for child in node.children:
                    save_node(child, node.id, depth + 1)

            for node in assignments:
                save_node(node, None, 0)

    def save_merger_verdicts(self, run_id: str, rows: list[dict]) -> None:
        if not rows:
            return
        now = _now_iso()
        with self._transaction():
            self._conn.executemany(
                """
                INSERT INTO merger_verdicts
                    (run_id, a_id, b_id, similarity, decision, parent, reason,
                     a_label, b_label, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, a_id, b_id) DO UPDATE SET
                    similarity=excluded.similarity, decision=excluded.decision,
                    parent=excluded.parent, reason=excluded.reason,
                    a_label=excluded.a_label, b_label=excluded.b_label,
                    created_at=excluded.created_at
                """,
                [
                    (
                        run_id, r["a_id"], r["b_id"], float(r.get("similarity", 0.0)),
                        r["decision"], r.get("parent"), r.get("reason") or "",
                        r.get("a_label") or "", r.get("b_label") or "", now,
                    )
                    for r in rows
                ],
            )

    def get_merger_verdicts(self, run_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM merger_verdicts"
        params: tuple = ()
        if run_id is not None:
            sql += " WHERE run_id=?"
            params = (run_id,)
        sql += " ORDER BY created_at, similarity DESC"
        return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def get_name(self, fingerprint: str) -> tuple[str, str] | None:
        row = self._conn.execute(
            "SELECT name, summary FROM cluster_names WHERE fingerprint=?",
            (fingerprint,),
        ).fetchone()
        return (row["name"], row["summary"]) if row else None

    def save_name(self, fingerprint: str, name: str, summary: str) -> None:
        with self._transaction():
            self._conn.execute(
                """
                INSERT INTO cluster_names (fingerprint, name, summary, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    name=excluded.name,
                    summary=excluded.summary,
                    updated_at=excluded.updated_at
                """,
                (fingerprint, name, summary, _now_iso()),
            )

    def get_compiled_note(self, cache_key: str) -> tuple[str, list[float]] | None:
        row = self._conn.execute(
            "SELECT text, embedding FROM compiled_notes WHERE cache_key=?",
            (cache_key,),
        ).fetchone()
        if not row:
            return None
        return row["text"], json.loads(row["embedding"])

    def save_compiled_note(
        self,
        cache_key: str,
        kind: str,
        text: str,
        embedding: list[float],
        prompt_version: str,
        *,
        members: list[str] | set[str] | None = None,
        drift: int = 0,
        origin_key: str | None = None,
    ) -> None:
        """Persist a compiled note. ``members`` (content hashes the note was
        synthesized from) enables overlap-tolerant reuse on later compiles;
        omit it to store an exact-key-only row. ``origin_key`` defaults to
        ``cache_key`` (a freshly synthesized note is its own origin)."""
        member_set = sorted(set(members)) if members else []
        with self._transaction():
            self._conn.execute(
                """
                INSERT INTO compiled_notes
                    (cache_key, kind, text, embedding, prompt_version, updated_at,
                     member_count, drift, origin_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    kind=excluded.kind,
                    text=excluded.text,
                    embedding=excluded.embedding,
                    prompt_version=excluded.prompt_version,
                    updated_at=excluded.updated_at,
                    member_count=excluded.member_count,
                    drift=excluded.drift,
                    origin_key=excluded.origin_key
                """,
                (cache_key, kind, text, json.dumps(embedding),
                 prompt_version, _now_iso(),
                 len(member_set) if member_set else None, int(drift),
                 origin_key or cache_key),
            )
            self._conn.execute(
                "DELETE FROM compiled_note_members WHERE cache_key=?", (cache_key,)
            )
            if member_set:
                self._conn.executemany(
                    "INSERT OR IGNORE INTO compiled_note_members "
                    "(cache_key, kind, member_hash) VALUES (?, ?, ?)",
                    [(cache_key, kind, h) for h in member_set],
                )

    def find_similar_compiled_note(
        self,
        kind: str,
        prompt_version: str,
        members: list[str] | set[str],
        *,
        min_overlap: float,
        max_drift: int,
    ) -> dict | None:
        """Best cached note of ``kind`` whose synthesized member set overlaps
        ``members`` by Jaccard ≥ ``min_overlap`` and has drifted fewer than
        ``max_drift`` times. Returns ``{"cache_key", "origin_key", "text",
        "embedding", "members", "drift", "overlap"}`` or None.

        Overlap is always measured against the member set the LLM actually
        saw (carried forward verbatim on reuse), so repeated small changes
        cannot compound into unbounded staleness."""
        current = set(members)
        if not current or min_overlap <= 0:
            return None
        hits: dict[str, int] = {}
        hashes = sorted(current)
        # Keep each IN-list well under SQLite's bound-parameter cap.
        for i in range(0, len(hashes), 500):
            batch = hashes[i:i + 500]
            marks = ",".join("?" * len(batch))
            for row in self._conn.execute(
                f"""
                SELECT cache_key, COUNT(*) AS n
                FROM compiled_note_members
                WHERE kind=? AND member_hash IN ({marks})
                GROUP BY cache_key
                """,
                (kind, *batch),
            ).fetchall():
                hits[row["cache_key"]] = hits.get(row["cache_key"], 0) + int(row["n"])
        if not hits:
            return None
        best: dict | None = None
        for cache_key, n in sorted(hits.items(), key=lambda kv: -kv[1])[:10]:
            row = self._conn.execute(
                "SELECT text, embedding, prompt_version, member_count, drift, origin_key "
                "FROM compiled_notes WHERE cache_key=?",
                (cache_key,),
            ).fetchone()
            if not row or row["prompt_version"] != prompt_version:
                continue
            if int(row["drift"] or 0) >= max_drift:
                continue
            origin_count = int(row["member_count"] or 0)
            union = len(current) + origin_count - n
            overlap = n / union if union else 0.0
            if overlap < min_overlap:
                continue
            if best is None or overlap > best["overlap"]:
                best = {
                    "cache_key": cache_key,
                    "origin_key": row["origin_key"] or cache_key,
                    "text": row["text"],
                    "embedding": json.loads(row["embedding"]),
                    "drift": int(row["drift"] or 0),
                    "overlap": overlap,
                }
        if best is None:
            return None
        best["members"] = [
            r["member_hash"]
            for r in self._conn.execute(
                "SELECT member_hash FROM compiled_note_members WHERE cache_key=?",
                (best["cache_key"],),
            ).fetchall()
        ]
        return best


    def bump_compiled_note_drift(self, origin_key: str) -> int:
        """Increment ``drift`` on every row descending from ``origin_key`` and
        return the new value. Called on each fuzzy reuse so the cap bounds
        total reuses of one synthesized text, not just the length of a chain."""
        with self._transaction():
            self._conn.execute(
                "UPDATE compiled_notes SET drift = drift + 1 WHERE origin_key=?",
                (origin_key,),
            )
            row = self._conn.execute(
                "SELECT MAX(drift) AS d FROM compiled_notes WHERE origin_key=?",
                (origin_key,),
            ).fetchone()
        return int(row["d"] or 0)

    def get_position(self, node_id: str) -> tuple[float, float] | None:
        row = self._conn.execute(
            "SELECT x, z FROM layout_seeds WHERE node_id=?",
            (node_id,),
        ).fetchone()
        return (float(row["x"]), float(row["z"])) if row else None

    def save_position(self, node_id: str, x: float, z: float) -> None:
        with self._transaction():
            self._conn.execute(
                """
                INSERT INTO layout_seeds (node_id, x, z, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    x=excluded.x,
                    z=excluded.z,
                    updated_at=excluded.updated_at
                """,
                (node_id, x, z, _now_iso()),
            )
