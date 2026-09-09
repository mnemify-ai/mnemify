"""Unit coverage for chunk-level semantic search (ask_chunks.py) and the
embedding-hash stamping read/write path in the store."""

from __future__ import annotations

from src.api.ask_chunks import (
    MIN_CHUNK_SCORE,
    build_index,
    search_index,
)
from src.terrain.utils.models import TerrainChunk
from src.terrain.utils.store import TerrainStore
from src.utils.hashing import short_hash


def _chunk(chunk_id: str, doc_id: str, content: str = "text") -> TerrainChunk:
    return TerrainChunk(
        id=chunk_id,
        doc_id=doc_id,
        source_type="notion",
        source_id="src-1",
        doc_title="Doc",
        content=content,
        content_hash=f"sha256:{chunk_id}",
    )


def _store_with_vectors(rows: list[tuple[str, str, list[float]]]) -> TerrainStore:
    """rows: (chunk_id, doc_id, vector)."""
    store = TerrainStore(":memory:")
    store.upsert_chunks([_chunk(cid, did) for cid, did, _ in rows])
    mapping = {}
    for cid, _did, vec in rows:
        ehash = f"eh-{cid}"
        store.save_embedding(ehash, "test-model", vec)
        mapping[cid] = ehash
    store.save_chunk_embedding_hashes(mapping)
    return store


# ── store: stamping round-trip ───────────────────────────────────────


def test_chunk_vectors_round_trip():
    store = _store_with_vectors([
        ("ch-1", "doc-a", [1.0, 0.0]),
        ("ch-2", "doc-b", [0.0, 1.0]),
    ])
    rows = store.get_chunk_vectors()
    assert {r["id"] for r in rows} == {"ch-1", "ch-2"}
    assert all(len(r["vector"]) == 2 for r in rows)


def test_unstamped_chunks_are_skipped():
    store = TerrainStore(":memory:")
    store.upsert_chunks([_chunk("ch-old", "doc-old")])  # no embedding_hash
    assert store.get_chunk_vectors() == []


# ── index build + search ─────────────────────────────────────────────


def test_search_ranks_by_cosine_and_maps_note_ids():
    store = _store_with_vectors([
        ("ch-hit", "doc-a", [1.0, 0.0]),
        ("ch-mid", "doc-b", [0.7, 0.7]),
        ("ch-miss", "doc-c", [0.0, 1.0]),
    ])
    index = build_index(store)
    hits = search_index(index, [1.0, 0.0], k=3)
    assert [h.chunk_id for h in hits] == ["ch-hit", "ch-mid"]  # ch-miss under floor
    assert hits[0].score > hits[1].score
    assert hits[0].note_node_id == f"n-{short_hash('doc-a', 8)}"


def test_search_applies_score_floor():
    store = _store_with_vectors([("ch-1", "doc-a", [MIN_CHUNK_SCORE / 2, 1.0])])
    index = build_index(store)
    assert search_index(index, [1.0, 0.0], k=5) == []


def test_search_dim_mismatch_returns_empty():
    store = _store_with_vectors([("ch-1", "doc-a", [1.0, 0.0])])
    index = build_index(store)
    assert search_index(index, [1.0, 0.0, 0.0], k=5) == []


def test_mixed_dim_vectors_keep_dominant():
    store = _store_with_vectors([
        ("ch-1", "doc-a", [1.0, 0.0]),
        ("ch-2", "doc-b", [0.9, 0.1]),
        ("ch-stale", "doc-c", [1.0, 0.0, 0.0]),  # old-model leftover
    ])
    index = build_index(store)
    assert index.dim == 2
    assert index.size == 2


def test_empty_store_yields_empty_index():
    index = build_index(TerrainStore(":memory:"))
    assert index.size == 0
    assert search_index(index, [1.0, 0.0]) == []
