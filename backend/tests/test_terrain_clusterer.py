from __future__ import annotations

import numpy as np

from src.terrain.utils import clusterer as clusterer_module
from src.terrain.utils.clusterer import TerrainClusterer
from src.terrain.utils.namer import ClusterNamer
from src.terrain.utils.models import ChunkFeatures, EnrichedChunk, TerrainChunk
from src.terrain.utils.store import TerrainStore


def enriched_chunk(
    chunk_id: str,
    embedding: list[float],
    *,
    product: str = "Sitelens",
    summary: str = "model training research",
) -> EnrichedChunk:
    return EnrichedChunk(
        chunk=TerrainChunk(
            id=chunk_id,
            doc_id=f"doc-{chunk_id}",
            source_type="notion",
            source_id=f"source-{chunk_id}",
            doc_title=f"Doc {chunk_id}",
            content=summary,
            content_hash=f"hash-{chunk_id}",
        ),
        features=ChunkFeatures(
            summary=summary,
            products=[product] if product else [],
            tags=summary.split()[:4],
            theme="Products" if product else "General",
            subtopic=product or "General",
        ),
        embedding=embedding,
    )


def test_clusterer_builds_top_level_tree_from_hdbscan(monkeypatch):
    captured: dict[str, np.ndarray] = {}

    class FakeHDBSCAN:
        def __init__(self, *, min_cluster_size: int, min_samples: int, copy: bool):
            assert min_cluster_size == 5
            assert min_samples == 3
            assert copy is False

        def fit_predict(self, embeddings: np.ndarray) -> np.ndarray:
            captured["embeddings"] = embeddings
            return np.asarray([0, 0, 1, 1, -1, -1])

    monkeypatch.setattr("src.terrain.utils.clusterer.HDBSCAN", FakeHDBSCAN)

    chunks = [
        enriched_chunk("a", [1.0, 0.0], product=""),
        enriched_chunk("b", [0.9, 0.1], product=""),
        enriched_chunk("c", [0.0, 1.0], product=""),
        enriched_chunk("d", [0.1, 0.9], product=""),
        enriched_chunk("e", [0.5, 0.5], product=""),
        enriched_chunk("f", [0.4, 0.6], product=""),
    ]

    roots = TerrainClusterer().cluster(chunks)

    assert captured["embeddings"].dtype == np.float32
    assert [sorted(root.chunk_ids) for root in roots] == [
        ["a", "b", "e"],
        ["c", "d", "f"],
    ]
    assert all(root.id.startswith("node_") for root in roots)
    assert all(root.children == [] for root in roots)


def test_clusterer_uses_project_clustering_constants():
    assert clusterer_module.COHERENCE_STOP_THRESHOLD == 0.75
    assert clusterer_module.MIN_CLUSTER_SIZE == 5
    assert clusterer_module.MIN_SAMPLES == 3


def test_clusterer_does_not_replace_hdbscan_with_product_groups(monkeypatch):
    class FakeHDBSCAN:
        def __init__(self, *, min_cluster_size: int, min_samples: int, copy: bool):
            pass

        def fit_predict(self, embeddings: np.ndarray) -> np.ndarray:
            return np.asarray([0, 0, 1, 1, -1, -1])

    monkeypatch.setattr("src.terrain.utils.clusterer.HDBSCAN", FakeHDBSCAN)

    chunks = [
        enriched_chunk("a", [1.0, 0.0], product="Sitelens"),
        enriched_chunk("b", [0.9, 0.1], product="Sitelens"),
        enriched_chunk("c", [0.0, 1.0], product="Mnemify"),
        enriched_chunk("d", [0.1, 0.9], product="Mnemify"),
        enriched_chunk("e", [0.5, 0.5], product="Atlas"),
        enriched_chunk("f", [0.4, 0.6], product="Atlas"),
    ]

    roots = TerrainClusterer().cluster(chunks)

    assert [sorted(root.chunk_ids) for root in roots] == [
        ["a", "b", "e"],
        ["c", "d", "f"],
    ]


def test_clusterer_stops_for_small_cluster():
    chunks = [
        enriched_chunk(str(i), [float(i), 1.0], product="")
        for i in range(clusterer_module.MAX_LEAF_CHUNKS)
    ]

    root = TerrainClusterer()._build_node(chunks, path="root", depth=0)

    assert root.children == []
    assert len(root.chunk_ids) == clusterer_module.MAX_LEAF_CHUNKS


def test_clusterer_stops_for_semantically_coherent_cluster():
    chunks = [
        enriched_chunk(str(i), [1.0, 0.001])
        for i in range(clusterer_module.MAX_LEAF_CHUNKS + 1)
    ]

    root = TerrainClusterer()._build_node(chunks, path="root", depth=0)

    assert root.children == []


def test_clusterer_recurses_for_dense_incoherent_cluster(monkeypatch):
    class FakeHDBSCAN:
        def __init__(self, *, min_cluster_size: int, min_samples: int, copy: bool):
            pass

        def fit_predict(self, embeddings: np.ndarray) -> np.ndarray:
            split = len(embeddings) // 2
            return np.asarray([0] * split + [1] * (len(embeddings) - split))

    monkeypatch.setattr("src.terrain.utils.clusterer.HDBSCAN", FakeHDBSCAN)
    chunks = [
        enriched_chunk(str(i), [1.0, 0.0] if i % 2 == 0 else [0.0, 1.0])
        for i in range(clusterer_module.MAX_LEAF_CHUNKS + 2)
    ]

    root = TerrainClusterer()._build_node(chunks, path="root", depth=0)

    assert len(root.children) == 2
    assert sorted(len(child.chunk_ids) for child in root.children) == [16, 16]


def test_clusterer_keeps_all_noise_as_single_leaf(monkeypatch):
    class FakeHDBSCAN:
        def __init__(self, *, min_cluster_size: int, min_samples: int, copy: bool):
            pass

        def fit_predict(self, embeddings: np.ndarray) -> np.ndarray:
            return np.full(len(embeddings), -1, dtype=np.int32)

    monkeypatch.setattr("src.terrain.utils.clusterer.HDBSCAN", FakeHDBSCAN)
    chunks = [
        enriched_chunk(
            str(i),
            [1.0, 0.0] if i % 2 == 0 else [0.0, 1.0],
            product="Sitelens" if i % 2 == 0 else "Mnemify",
            summary="customer contract sales"
            if i % 2 == 0
            else "model training research",
        )
        for i in range(clusterer_module.MAX_LEAF_CHUNKS + 2)
    ]

    root = TerrainClusterer()._build_node(chunks, path="root", depth=0)

    assert root.children == []


def test_clusterer_keeps_noise_as_non_empty_child(monkeypatch):
    class FakeHDBSCAN:
        def __init__(self, *, min_cluster_size: int, min_samples: int, copy: bool):
            pass

        def fit_predict(self, embeddings: np.ndarray) -> np.ndarray:
            return np.asarray([0, 0, 0, 0, 0, -1, -1])

    monkeypatch.setattr("src.terrain.utils.clusterer.HDBSCAN", FakeHDBSCAN)
    chunks = [
        enriched_chunk(str(i), [float(i), 1.0], product="")
        for i in range(7)
    ]

    roots = TerrainClusterer().cluster(chunks)

    assert [sorted(root.chunk_ids) for root in roots] == [
        ["0", "1", "2", "3", "4", "5", "6"],
    ]


def test_clusterer_assigns_chunks_to_multiple_top_level_regions():
    clusterer = TerrainClusterer()
    bridge = enriched_chunk("bridge", [0.7, 0.7], product="")
    roots = [
        clusterer._build_node(
            [enriched_chunk("a", [1.0, 0.0], product=""), bridge],
            path="root_a",
            depth=0,
        ),
        clusterer._build_node(
            [enriched_chunk("b", [0.0, 1.0], product="")],
            path="root_b",
            depth=0,
        ),
    ]
    chunks = [
        enriched_chunk("a", [1.0, 0.0], product=""),
        enriched_chunk("b", [0.0, 1.0], product=""),
        bridge,
    ]

    clusterer.assign_multi_region(chunks, roots, threshold=0.45)

    bridge = next(item for item in chunks if item.chunk.id == "bridge")
    assert set(bridge.chunk.region_assignments) == {roots[0].id, roots[1].id}
    assert "bridge" in roots[0].chunk_ids
    assert "bridge" not in roots[1].chunk_ids


def test_clusterer_does_not_add_below_threshold_secondary_fallback():
    clusterer = TerrainClusterer()
    weak = enriched_chunk("weak", [0.2, 0.0], product="")
    roots = [
        clusterer._build_node(
            [enriched_chunk("a", [1.0, 0.0], product=""), weak],
            path="root_a",
            depth=0,
        ),
        clusterer._build_node(
            [enriched_chunk("b", [0.0, 1.0], product="")],
            path="root_b",
            depth=0,
        ),
    ]
    chunks = [
        enriched_chunk("a", [1.0, 0.0], product=""),
        enriched_chunk("b", [0.0, 1.0], product=""),
        weak,
    ]

    clusterer.assign_multi_region(chunks, roots, threshold=0.9)

    weak = next(item for item in chunks if item.chunk.id == "weak")
    assert weak.chunk.region_assignments == [roots[0].id]
    assert "weak" not in roots[1].chunk_ids


def _doc_id(item) -> str:
    return item.chunk.doc_id


def test_cluster_with_containers_one_region_per_top_folder(monkeypatch):
    # Coherent embeddings so leaf folders stay single regions (no sub-split).
    monkeypatch.setattr(clusterer_module, "MAX_LEAF_CHUNKS", 1000)
    chunks = [
        enriched_chunk("a", [1.0, 0.0], product=""),
        enriched_chunk("b", [0.9, 0.1], product=""),
        enriched_chunk("c", [0.0, 1.0], product=""),
        enriched_chunk("d", [0.1, 0.9], product=""),
    ]
    container_by_doc = {
        "doc-a": ["01-Architecture"],
        "doc-b": ["01-Architecture"],
        "doc-c": ["02-Hiring"],
        "doc-d": ["02-Hiring"],
    }

    roots = TerrainClusterer().cluster_with_containers(chunks, container_by_doc)

    assert len(roots) == 2
    assert [sorted(r.chunk_ids) for r in roots] == [["a", "b"], ["c", "d"]]
    assert all(r.children == [] for r in roots)


def test_cluster_with_containers_nests_subfolders(monkeypatch):
    monkeypatch.setattr(clusterer_module, "MAX_LEAF_CHUNKS", 1000)
    chunks = [
        enriched_chunk("a", [1.0, 0.0], product=""),
        enriched_chunk("b", [0.9, 0.1], product=""),
    ]
    container_by_doc = {
        "doc-a": ["Projects"],
        "doc-b": ["Projects", "Alpha"],
    }

    roots = TerrainClusterer().cluster_with_containers(chunks, container_by_doc)

    assert len(roots) == 1
    projects = roots[0]
    assert sorted(projects.chunk_ids) == ["a", "b"]
    # Direct note of Projects + the Alpha subfolder both appear as children.
    child_ids = {tuple(sorted(c.chunk_ids)) for c in projects.children}
    assert child_ids == {("a",), ("b",)}


def test_cluster_with_containers_falls_back_when_no_containers():
    chunks = [
        enriched_chunk(str(i), [float(i), 1.0], product="")
        for i in range(7)
    ]
    container_by_doc: dict[str, list[str]] = {}

    with_containers = TerrainClusterer().cluster_with_containers(chunks, container_by_doc)
    legacy = TerrainClusterer().cluster(chunks)

    assert [sorted(r.chunk_ids) for r in with_containers] == [
        sorted(r.chunk_ids) for r in legacy
    ]


def test_cluster_with_containers_routes_unfiled_through_hdbscan(monkeypatch):
    monkeypatch.setattr(clusterer_module, "MAX_LEAF_CHUNKS", 1000)

    class FakeHDBSCAN:
        def __init__(self, **_kwargs):
            pass

        def fit_predict(self, embeddings: np.ndarray) -> np.ndarray:
            return np.asarray([0, 0, 1, 1, 1])

    monkeypatch.setattr("src.terrain.utils.clusterer.HDBSCAN", FakeHDBSCAN)
    chunks = [
        enriched_chunk("a", [1.0, 0.0], product=""),
        enriched_chunk("u0", [1.0, 0.0], product=""),
        enriched_chunk("u1", [0.9, 0.1], product=""),
        enriched_chunk("u2", [0.0, 1.0], product=""),
        enriched_chunk("u3", [0.1, 0.9], product=""),
        enriched_chunk("u4", [0.2, 0.8], product=""),
    ]
    container_by_doc = {"doc-a": ["Filed"]}

    roots = TerrainClusterer().cluster_with_containers(chunks, container_by_doc)

    by_ids = sorted(sorted(r.chunk_ids) for r in roots)
    # One folder root ("Filed") + two HDBSCAN roots for the unfiled chunks.
    assert ["a"] in by_ids
    assert ["u0", "u1"] in by_ids
    assert ["u2", "u3", "u4"] in by_ids


def test_tag_blurb_uses_region_lens():
    store = TerrainStore(":memory:")
    try:
        namer = ClusterNamer(store)
        _label, blurb = namer.name_tag(
            [enriched_chunk("terna", [0.7, 0.7], summary="contract renewal metrics")],
            region_name="Customers",
            region_terms=["Terna", "renewal", "contract"],
        )
    finally:
        store.close()

    assert blurb.startswith("In Customers,")


def test_local_namer_does_not_keyword_route_region_names():
    store = TerrainStore(":memory:")
    try:
        namer = ClusterNamer(store)
        name, _summary = namer.name_region(
            [
                enriched_chunk(
                    "research",
                    [1.0, 0.0],
                    product="",
                    summary="model training architecture roadmap",
                )
            ]
        )
    finally:
        store.close()

    assert name != "R&D"
