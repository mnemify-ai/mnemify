"""Chunk-level semantic search for /api/ask.

Node-level retrieval only ever compares the query against compiled-summary
embeddings (tags/regions/signals) — a fact that survives neither the chunk
summary nor the compiled-note distillation is unfindable. This module
searches the *raw chunk* vectors the compile already produced, so matched
chunks can seed their parent note nodes with a real semantic score and
steer expansion at exactly the right chunks.

Requires ``chunks.embedding_hash`` stamping (compiles from v0.8 on). Older
``terrain.db`` files have NULL hashes → the index is empty and chunk search
silently contributes nothing until the next compile (which is cheap — all
caches hit).

The vector index is built once per ``terrain.db`` mtime and cached
in-process.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from src.terrain.utils.store import TerrainStore
from src.utils.hashing import short_hash

logger = logging.getLogger(__name__)

# How many chunks a query may seed, and the cosine floor below which a chunk
# match is considered noise rather than evidence.
CHUNK_SEARCH_K = 8
MIN_CHUNK_SCORE = 0.2

_TERRAIN_DB_PATH = Path(".mnemify/terrain.db")


@dataclass
class ChunkHit:
    chunk_id: str
    doc_id: str
    note_node_id: str
    score: float


@dataclass
class ChunkIndex:
    """L2-normalized chunk vectors + aligned metadata."""

    chunk_ids: list[str] = field(default_factory=list)
    doc_ids: list[str] = field(default_factory=list)
    matrix: np.ndarray | None = None  # shape (n, dim), rows normalized
    dim: int = 0

    @property
    def size(self) -> int:
        return len(self.chunk_ids)


_CACHE_LOCK = threading.Lock()
_INDEX_CACHE: dict[str, tuple[float, ChunkIndex]] = {}


def search(
    query_embedding: list[float],
    *,
    db_path: Path = _TERRAIN_DB_PATH,
    k: int = CHUNK_SEARCH_K,
) -> list[ChunkHit]:
    """Top-k chunks by cosine against the query. Best-effort: any failure
    (missing db, no stamped hashes, dimension mismatch) returns ``[]`` so
    the caller falls back to node-level retrieval alone."""
    if not query_embedding:
        return []
    try:
        index = _get_index(db_path)
    except Exception:  # noqa: BLE001
        logger.exception("ask chunks: index build failed; skipping chunk search")
        return []
    return search_index(index, query_embedding, k=k)


def search_index(
    index: ChunkIndex, query_embedding: list[float], *, k: int = CHUNK_SEARCH_K
) -> list[ChunkHit]:
    if index.matrix is None or index.size == 0:
        return []
    if len(query_embedding) != index.dim:
        # Different embedding space (e.g. local-hash query vs OpenAI-compiled
        # chunks). The route's dimension guard normally catches this against
        # the graph first; stay silent here regardless.
        return []
    q = np.asarray(query_embedding, dtype=np.float32)
    norm = float(np.linalg.norm(q)) or 1.0
    scores = index.matrix @ (q / norm)
    k = min(k, index.size)
    top = np.argpartition(-scores, k - 1)[:k]
    top = top[np.argsort(-scores[top])]
    hits: list[ChunkHit] = []
    for i in top:
        score = float(scores[i])
        if score < MIN_CHUNK_SCORE:
            break  # sorted descending — everything after is noise too
        doc_id = index.doc_ids[i]
        hits.append(
            ChunkHit(
                chunk_id=index.chunk_ids[i],
                doc_id=doc_id,
                note_node_id=f"n-{short_hash(doc_id, 8)}",
                score=round(score, 4),
            )
        )
    return hits


def build_index(store: TerrainStore) -> ChunkIndex:
    """Build the normalized vector index from stamped chunk rows. Vectors
    whose dimension differs from the dominant one (mixed-model leftovers)
    are skipped."""
    rows = store.get_chunk_vectors()
    if not rows:
        return ChunkIndex()
    dims: dict[int, int] = {}
    for row in rows:
        dims[len(row["vector"])] = dims.get(len(row["vector"]), 0) + 1
    dim = max(dims, key=lambda d: dims[d])
    kept = [r for r in rows if len(r["vector"]) == dim]
    matrix = np.asarray([r["vector"] for r in kept], dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return ChunkIndex(
        chunk_ids=[r["id"] for r in kept],
        doc_ids=[r["doc_id"] for r in kept],
        matrix=matrix / norms,
        dim=dim,
    )


def _get_index(db_path: Path) -> ChunkIndex:
    if not db_path.is_file():
        return ChunkIndex()
    key = str(db_path.resolve())
    mtime = db_path.stat().st_mtime
    with _CACHE_LOCK:
        cached = _INDEX_CACHE.get(key)
        if cached is not None and cached[0] == mtime:
            return cached[1]
    store = TerrainStore(db_path)
    try:
        index = build_index(store)
    finally:
        store.close()
    logger.info(
        "ask chunks: indexed %s chunk vectors (dim=%s) from %s",
        index.size, index.dim, db_path,
    )
    with _CACHE_LOCK:
        _INDEX_CACHE[key] = (mtime, index)
    return index
