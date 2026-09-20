"""Tests for TerrainStore.graph_node_vectors — the float32 sqlite home for
raw graph-node embeddings that V0.9 strips out of terrain.json."""

from __future__ import annotations

from src.terrain.utils.store import TerrainStore


def test_graph_node_vectors_float32_roundtrip(tmp_path):
    store = TerrainStore(tmp_path / "terrain.db")
    try:
        vectors = {
            "graph.n1": [0.123456789, -0.987654321, 3.14159265],
            "graph.n2": [1.5, -2.5, 0.0],
        }
        store.replace_graph_node_vectors(vectors, model="text-embedding-3-large")
        loaded = store.load_graph_node_vectors()
        assert set(loaded) == set(vectors)
        for node_id, expected in vectors.items():
            for got, want in zip(loaded[node_id], expected):
                # float32 quantization: relative tolerance ~1e-6 is plenty
                # for cosine ranking.
                assert abs(got - want) <= 1e-6 * max(1.0, abs(want))
    finally:
        store.close()


def test_replace_graph_node_vectors_clears_stale_rows(tmp_path):
    store = TerrainStore(tmp_path / "terrain.db")
    try:
        store.replace_graph_node_vectors({"old.node": [1.0, 2.0]})
        store.replace_graph_node_vectors({"new.node": [3.0, 4.0]})
        loaded = store.load_graph_node_vectors()
        # Full-replace semantics: ids from a prior compile never linger.
        assert set(loaded) == {"new.node"}
    finally:
        store.close()


def test_load_graph_node_vectors_empty_table(tmp_path):
    store = TerrainStore(tmp_path / "terrain.db")
    try:
        assert store.load_graph_node_vectors() == {}
    finally:
        store.close()


# ── overlap-tolerant compiled-note reuse ─────────────────────────────


def _members(n: int, prefix: str = "h") -> list[str]:
    return [f"{prefix}{i}" for i in range(n)]


def test_find_similar_compiled_note_hits_on_high_overlap(tmp_path):
    store = TerrainStore(tmp_path / "terrain.db")
    try:
        store.save_compiled_note(
            "k1", "tag", "note text", [0.1, 0.2], "v1", members=_members(20)
        )
        # 19 shared + 1 new → Jaccard 19/21 ≈ 0.905
        current = _members(19) + ["new1"]
        hit = store.find_similar_compiled_note(
            "tag", "v1", current, min_overlap=0.9, max_drift=3
        )
        assert hit is not None
        assert hit["cache_key"] == "k1"
        assert hit["text"] == "note text"
        assert hit["embedding"] == [0.1, 0.2]
        assert hit["drift"] == 0
        assert sorted(hit["members"]) == sorted(_members(20))
        assert abs(hit["overlap"] - 19 / 21) < 1e-9
    finally:
        store.close()


def test_find_similar_compiled_note_misses_on_low_overlap(tmp_path):
    store = TerrainStore(tmp_path / "terrain.db")
    try:
        store.save_compiled_note(
            "k1", "tag", "note text", [0.1], "v1", members=_members(10)
        )
        # 5 shared of 10 → 0.5 overlap: miss at 0.9 threshold.
        current = _members(5) + _members(5, "x")
        assert store.find_similar_compiled_note(
            "tag", "v1", current, min_overlap=0.9, max_drift=3
        ) is None
    finally:
        store.close()


def test_find_similar_compiled_note_respects_kind_version_and_drift(tmp_path):
    store = TerrainStore(tmp_path / "terrain.db")
    try:
        m = _members(20)
        store.save_compiled_note("k_kind", "region", "r", [0.1], "v1", members=m)
        store.save_compiled_note("k_ver", "tag", "t", [0.1], "v0", members=m)
        store.save_compiled_note(
            "k_drift", "tag", "t", [0.1], "v1", members=m, drift=3
        )
        current = m[:19] + ["new"]
        # Wrong kind, wrong prompt version, and drift at the cap all miss.
        assert store.find_similar_compiled_note(
            "tag", "v1", current, min_overlap=0.9, max_drift=3
        ) is None
        # Raising the cap makes the drifted row eligible again.
        hit = store.find_similar_compiled_note(
            "tag", "v1", current, min_overlap=0.9, max_drift=4
        )
        assert hit is not None and hit["cache_key"] == "k_drift"
    finally:
        store.close()


def test_find_similar_compiled_note_picks_best_overlap(tmp_path):
    store = TerrainStore(tmp_path / "terrain.db")
    try:
        m = _members(20)
        store.save_compiled_note("worse", "tag", "a", [0.1], "v1", members=m[:18] + ["p", "q"])
        store.save_compiled_note("better", "tag", "b", [0.1], "v1", members=m)
        hit = store.find_similar_compiled_note(
            "tag", "v1", m[:19] + ["new"], min_overlap=0.8, max_drift=3
        )
        assert hit is not None and hit["cache_key"] == "better"
    finally:
        store.close()


def test_find_similar_compiled_note_handles_large_member_sets(tmp_path):
    """IN-lists are batched; >500 members must not trip SQLite's param cap."""
    store = TerrainStore(tmp_path / "terrain.db")
    try:
        m = _members(1500)
        store.save_compiled_note("big", "region", "r", [0.1], "v1", members=m)
        hit = store.find_similar_compiled_note(
            "region", "v1", m[:1450] + _members(10, "n"), min_overlap=0.9, max_drift=3
        )
        assert hit is not None and hit["cache_key"] == "big"
    finally:
        store.close()


def test_save_compiled_note_without_members_never_fuzzy_matches(tmp_path):
    store = TerrainStore(tmp_path / "terrain.db")
    try:
        store.save_compiled_note("legacy", "tag", "t", [0.1], "v1")
        assert store.get_compiled_note("legacy") == ("t", [0.1])
        assert store.find_similar_compiled_note(
            "tag", "v1", _members(5), min_overlap=0.5, max_drift=3
        ) is None
    finally:
        store.close()


def test_find_similar_compiled_note_is_confined_to_one_identity(tmp_path):
    """Two sibling tags over the same documents (identical member sets) must
    never be handed each other's synthesized text."""
    store = TerrainStore(tmp_path / "t.db")
    try:
        m = [f"h{i}" for i in range(20)]
        store.save_compiled_note(
            "k_a", "tag", "About A", [0.1], "v1", members=m, identity="tag|alpha"
        )
        # Same identity, near-identical members: reuse.
        hit = store.find_similar_compiled_note(
            "tag", "v1", m[:19] + ["new"], min_overlap=0.9, max_drift=3, identity="tag|alpha"
        )
        assert hit is not None and hit["text"] == "About A"
        # Different identity, identical members: no reuse.
        assert store.find_similar_compiled_note(
            "tag", "v1", m, min_overlap=0.9, max_drift=3, identity="tag|beta"
        ) is None
        # Rows saved before identities existed never match an identity query.
        store.save_compiled_note("k_legacy", "tag", "old", [0.1], "v1", members=m)
        assert store.find_similar_compiled_note(
            "tag", "v1", m, min_overlap=0.9, max_drift=3, identity="tag|gamma"
        ) is None
    finally:
        store.close()
