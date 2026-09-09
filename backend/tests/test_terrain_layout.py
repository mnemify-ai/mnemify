from __future__ import annotations

import math

from src.terrain.utils.layout import TerrainLayout
from src.terrain.utils.models import (
    ChunkFeatures,
    ClusterTreeNode,
    EnrichedChunk,
    Position,
    TerrainChunk,
)
from src.terrain.utils.store import TerrainStore


def enriched_chunk(chunk_id: str, embedding: list[float]) -> EnrichedChunk:
    return EnrichedChunk(
        chunk=TerrainChunk(
            id=chunk_id,
            doc_id=f"doc-{chunk_id}",
            source_type="notion",
            source_id=f"source-{chunk_id}",
            doc_title=f"Doc {chunk_id}",
            content=f"content {chunk_id}",
            content_hash=f"hash-{chunk_id}",
        ),
        features=ChunkFeatures(summary=f"summary {chunk_id}"),
        embedding=embedding,
    )


def tree_node(node_id: str, chunk_ids: list[str]) -> ClusterTreeNode:
    return ClusterTreeNode(
        id=node_id,
        name="",
        position=Position(x=0.0, z=0.0),
        height=1,
        chunk_ids=chunk_ids,
        children=[],
    )


def distance(a: Position, b: Position) -> float:
    return math.hypot(a.x - b.x, a.z - b.z)


def test_semantic_positions_anchor_largest_region_at_origin():
    store = TerrainStore(":memory:")
    try:
        layout = TerrainLayout(store)
        nodes = [
            tree_node("near", ["near"]),
            tree_node("largest", ["a", "b"]),
            tree_node("far", ["far"]),
        ]
        chunks_by_node = {
            "largest": [
                enriched_chunk("a", [1.0, 0.0]),
                enriched_chunk("b", [0.98, 0.02]),
            ],
            "near": [enriched_chunk("near", [0.9, 0.1])],
            "far": [enriched_chunk("far", [-1.0, 0.0])],
        }

        positions = layout.semantic_positions(nodes, chunks_by_node, radius=100.0)
    finally:
        store.close()

    assert positions["largest"] == Position(x=0.0, z=0.0)
    assert distance(positions["largest"], positions["near"]) < distance(
        positions["largest"],
        positions["far"],
    )
    assert max(math.hypot(pos.x, pos.z) for pos in positions.values()) <= 100.0


def test_nested_positions_use_child_centroids_inside_parent():
    store = TerrainStore(":memory:")
    try:
        layout = TerrainLayout(store)
        child_nodes = [
            tree_node("large_child", ["a", "b"]),
            tree_node("small_child", ["c"]),
        ]
        chunks_by_node = {
            "large_child": [
                enriched_chunk("a", [1.0, 0.0]),
                enriched_chunk("b", [0.95, 0.05]),
            ],
            "small_child": [enriched_chunk("c", [0.0, 1.0])],
        }

        positions = layout.nested_positions(
            "parent",
            ["large_child", "small_child"],
            Position(x=20.0, z=-10.0),
            parent_radius=30.0,
            scale=0.5,
            child_nodes=child_nodes,
            chunks_by_node=chunks_by_node,
        )
    finally:
        store.close()

    assert positions["large_child"] == Position(x=20.0, z=-10.0)
    assert distance(positions["large_child"], positions["small_child"]) <= 15.0
