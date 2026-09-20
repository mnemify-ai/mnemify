"""Hydration of lean terrain.json artifacts in the /api/ask load path, plus
the one-time fat-artifact startup migration (V0.9 embedding strip)."""

from __future__ import annotations

import json
from pathlib import Path

from src.api import _migrate_fat_terrain_artifact
from src.api import routes_ask
from src.terrain.utils.store import TerrainStore

VEC_A = [1.0, 0.0, 0.0]
VEC_B = [0.0, 1.0, 0.0]


def _map_dict(nodes: list[dict], edges: list[dict]) -> dict:
    return {
        "version": 2,
        "schemaName": "cortex.brain-map",
        "workspace": "Test",
        "owner": {"name": "Tester", "role": "Engineer"},
        "generatedAt": "2026-08-26T00:00:00+00:00",
        "compiler": {"version": "0.2.0", "extractor": "", "clusterer": ""},
        "bounds": {"minX": -1, "maxX": 1, "minZ": -1, "maxZ": 1, "maxElevation": 1},
        "stats": {
            "regions": 0, "subRegionsTotal": 0, "tagsTotal": 0,
            "notes": 0, "sources": 0, "edges": 0,
        },
        "highlights": {},
        "tree": [],
        "edges": {"regionEdges": [], "tagEdges": []},
        "graph": {"nodes": nodes, "edges": edges},
    }


def _lean_nodes() -> list[dict]:
    return [
        {"id": "tag.a", "type": "tag", "label": "A", "layer": 2},
        {"id": "tag.b", "type": "tag", "label": "B", "layer": 2},
    ]


def _data_dir(tmp_path: Path) -> Path:
    """Where ``routes_ask`` resolves terrain.json / terrain.db.

    The autouse ``_isolated_mnemify_home`` fixture sets ``MNEMIFY_HOME`` to
    ``tmp_path``, so the data dir is ``tmp_path/.mnemify`` — the route reads
    it through ``src.paths`` at call time; there is no module constant to
    monkeypatch any more.
    """
    d = tmp_path / ".mnemify"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_artifact(dir_: Path, data: dict) -> Path:
    path = dir_ / "terrain.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_lean_artifact_hydrates_from_table(tmp_path):
    edges = [
        {
            "from": "tag.a",
            "to": "tag.b",
            "type": "co-occurs",
            "provenance": "extracted",
            "confidence": 1.0,
            "weight": 1.0,
        }
    ]
    data_dir = _data_dir(tmp_path)
    _write_artifact(data_dir, _map_dict(_lean_nodes(), edges))
    store = TerrainStore(data_dir / "terrain.db")
    try:
        store.replace_graph_node_vectors({"tag.a": VEC_A, "tag.b": VEC_B})
    finally:
        store.close()

    knowledge_map = routes_ask._load_knowledge_map()

    by_id = {n.id: n for n in knowledge_map.graph.nodes}
    assert by_id["tag.a"].embedding == VEC_A
    assert by_id["tag.b"].embedding == VEC_B
    # Context embeddings recomputed from raw vectors + edges.
    assert by_id["tag.a"].context_embedding is not None
    assert routes_ask._graph_embedding_dim(knowledge_map) == 3


def test_fat_artifact_skips_hydration(tmp_path):
    nodes = _lean_nodes()
    nodes[0]["embedding"] = VEC_A  # inline vector → pre-strip artifact
    data_dir = _data_dir(tmp_path)
    _write_artifact(data_dir, _map_dict(nodes, []))
    # Deliberately no terrain.db: a fat artifact must never need one.

    knowledge_map = routes_ask._load_knowledge_map()

    by_id = {n.id: n for n in knowledge_map.graph.nodes}
    assert by_id["tag.a"].embedding == VEC_A
    assert not (data_dir / "terrain.db").exists()


def test_lean_artifact_without_db_degrades(tmp_path):
    data_dir = _data_dir(tmp_path)
    _write_artifact(data_dir, _map_dict(_lean_nodes(), []))

    knowledge_map = routes_ask._load_knowledge_map()  # must not raise

    assert routes_ask._graph_embedding_dim(knowledge_map) is None
    # Hydration must not create an empty db as a side effect.
    assert not (data_dir / "terrain.db").exists()


def test_lean_artifact_with_empty_table_degrades(tmp_path):
    data_dir = _data_dir(tmp_path)
    _write_artifact(data_dir, _map_dict(_lean_nodes(), []))
    TerrainStore(data_dir / "terrain.db").close()  # tables exist, no rows

    knowledge_map = routes_ask._load_knowledge_map()  # must not raise

    assert routes_ask._graph_embedding_dim(knowledge_map) is None


def test_startup_migration_slims_fat_artifact(tmp_path):
    data_dir = _data_dir(tmp_path)
    nodes = _lean_nodes()
    nodes[0]["embedding"] = VEC_A
    nodes[0]["context_embedding"] = VEC_A
    nodes[1]["embedding"] = VEC_B
    path = _write_artifact(data_dir, _map_dict(nodes, []))

    _migrate_fat_terrain_artifact(data_dir)

    slimmed = json.loads(path.read_text(encoding="utf-8"))
    dumped = json.dumps(slimmed)
    assert '"embedding"' not in dumped
    assert '"context_embedding"' not in dumped
    store = TerrainStore(data_dir / "terrain.db")
    try:
        vectors = store.load_graph_node_vectors()
    finally:
        store.close()
    assert set(vectors) == {"tag.a", "tag.b"}

    # The migrated artifact hydrates like a native lean one.
    knowledge_map = routes_ask._load_knowledge_map()
    assert routes_ask._graph_embedding_dim(knowledge_map) == 3

    # Idempotent: a second run is a no-op.
    _migrate_fat_terrain_artifact(data_dir)
    assert json.loads(path.read_text(encoding="utf-8")) == slimmed


def test_migration_skips_when_nothing_compiled(tmp_path):
    _migrate_fat_terrain_artifact(tmp_path)  # no terrain.json — must not raise
    assert not (tmp_path / "terrain.db").exists()
