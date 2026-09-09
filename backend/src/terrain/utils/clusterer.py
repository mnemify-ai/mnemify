from __future__ import annotations

import logging
from collections import defaultdict

import numpy as np
from sklearn.cluster import HDBSCAN

from src.terrain.utils.models import ClusterTreeNode, EnrichedChunk, Position
from src.utils.hashing import short_hash


MAX_LEAF_CHUNKS = 30
COHERENCE_STOP_THRESHOLD = 0.75
MIN_CLUSTER_SIZE = 5
MIN_SAMPLES = 3
MULTI_REGION_SIMILARITY_THRESHOLD = 0.45
NOISE_ABSORPTION_THRESHOLD = 0.35

logger = logging.getLogger(__name__)


class TerrainClusterer:
    def cluster(self, chunks: list[EnrichedChunk]) -> list[ClusterTreeNode]:
        if not chunks:
            return []

        labels = self._hdbscan_labels(chunks)
        grouped = self._groups_from_labels(labels, chunks)

        roots: list[ClusterTreeNode] = []
        for label, members in sorted(grouped.items()):
            roots.append(self._build_node(members, path=f"root_{label}", depth=0))
        return roots

    def cluster_with_containers(
        self,
        chunks: list[EnrichedChunk],
        container_by_doc: dict[str, list[str]],
    ) -> list[ClusterTreeNode]:
        """Container-backbone clustering.

        Source-native containers (Obsidian folders, see ``container_path``)
        seed the top-level region structure: each top-level folder becomes a
        root, nested folders become nested regions. Inside a leaf folder the
        existing ``_build_node`` recursion still runs, so an oversized,
        incoherent folder is sub-split (and ``MAX_LEAF_CHUNKS`` is respected)
        for free. Documents with no container are clustered with today's
        HDBSCAN path so they scatter into semantic regions instead of one blob.

        Falls back ENTIRELY to ``cluster`` when no document carries a
        container — preserving current behavior for container-less sources.
        """
        if not chunks:
            return []

        foldered: dict[tuple[str, ...], list[EnrichedChunk]] = defaultdict(list)
        unfiled: list[EnrichedChunk] = []
        for item in chunks:
            path = tuple(container_by_doc.get(item.chunk.doc_id) or [])
            if path:
                foldered[path].append(item)
            else:
                unfiled.append(item)

        if not foldered:
            # No source structure at all → identical to the legacy path.
            return self.cluster(chunks)

        trie = self._container_trie(foldered)
        roots = [
            self._node_from_trie((segment,), node, depth=0)
            for segment, node in sorted(trie.items())
        ]
        # Container-less docs keep their semantic clustering (their own roots),
        # rather than being dumped into a single "Unfiled" blob.
        if unfiled:
            roots.extend(self.cluster(unfiled))
        return roots

    def _container_trie(
        self,
        foldered: dict[tuple[str, ...], list[EnrichedChunk]],
    ) -> dict[str, dict]:
        """Build a folder trie. Each node is ``{"direct": [...], "children":
        {segment: node}}`` where ``direct`` holds the chunks whose leaf folder
        is exactly that node's path."""
        root: dict[str, dict] = {}
        for path, items in foldered.items():
            level = root
            node: dict | None = None
            for segment in path:
                node = level.setdefault(segment, {"direct": [], "children": {}})
                level = node["children"]
            assert node is not None  # path is non-empty (foldered keys are truthy)
            node["direct"].extend(items)
        return root

    def _node_from_trie(
        self,
        segment_path: tuple[str, ...],
        node: dict,
        *,
        depth: int,
    ) -> ClusterTreeNode:
        direct: list[EnrichedChunk] = node["direct"]
        children_dict: dict[str, dict] = node["children"]
        path_str = "container_" + "/".join(segment_path)

        # Pure leaf folder (no subfolders): let the existing recursion decide
        # whether it stays one region or sub-splits on size + incoherence.
        if not children_dict:
            return self._build_node(direct, path=path_str, depth=depth)

        child_nodes: list[ClusterTreeNode] = [
            self._node_from_trie(segment_path + (segment,), child, depth=depth + 1)
            for segment, child in sorted(children_dict.items())
        ]
        # A folder with BOTH subfolders and its own notes: the direct notes
        # become a sibling sub-region so every chunk still lands in a leaf.
        if direct:
            child_nodes.insert(
                0, self._build_node(direct, path=f"{path_str}/__direct__", depth=depth + 1)
            )

        chunk_ids = sorted({cid for child in child_nodes for cid in child.chunk_ids})
        return ClusterTreeNode(
            id=self._node_id_from_ids(path_str, chunk_ids),
            name="",
            position=Position(x=0.0, z=0.0),
            height=1,
            chunk_ids=chunk_ids,
            children=child_nodes,
        )

    def assign_multi_region(
        self,
        chunks: list[EnrichedChunk],
        roots: list[ClusterTreeNode],
        *,
        threshold: float = MULTI_REGION_SIMILARITY_THRESHOLD,
    ) -> None:
        """Attach chunks to qualifying secondary top-level clusters.

        The recursive tree remains the primary layout/tag hierarchy. Top-level
        ``chunk_ids`` are primary HDBSCAN membership and are deliberately not
        mutated here; ``region_assignments`` records primary + secondary
        contextual appearances.
        """
        if not chunks or not roots:
            return

        chunks_by_id = {item.chunk.id: item for item in chunks}
        centroids: dict[str, np.ndarray] = {}
        for root in roots:
            members = [
                chunks_by_id[cid]
                for cid in root.chunk_ids
                if cid in chunks_by_id
            ]
            if members:
                centroids[root.id] = self._normalized_centroid(members)

        if not centroids:
            return

        primary_by_chunk: dict[str, set[str]] = defaultdict(set)
        for root in roots:
            for chunk_id in root.chunk_ids:
                primary_by_chunk[chunk_id].add(root.id)

        for item in chunks:
            primary_ids = primary_by_chunk.get(item.chunk.id, set())
            if not primary_ids:
                raise ValueError(
                    f"chunk {item.chunk.id} has no primary top-level region"
                )

            vector = self._normalized_vector(item.embedding)
            scores = {
                root_id: float(vector @ centroid)
                for root_id, centroid in centroids.items()
            }
            secondary_ids = [
                root_id
                for root_id, score in sorted(
                    scores.items(),
                    key=lambda pair: (-pair[1], pair[0]),
                )
                if root_id not in primary_ids and score >= threshold
            ]
            item.chunk.region_assignments = sorted(primary_ids | set(secondary_ids))

    def _build_node(
        self,
        chunks: list[EnrichedChunk],
        *,
        path: str,
        depth: int,
    ) -> ClusterTreeNode:
        node_id = self._node_id(path, chunks)
        chunk_ids = sorted(item.chunk.id for item in chunks)
        children: list[ClusterTreeNode] = []

        should_recurse = self._should_recurse(chunks)
        if should_recurse:
            labels = self._hdbscan_labels(chunks)
            grouped = self._groups_from_labels(labels, chunks)
            if len(grouped) >= 2:
                for label, members in sorted(grouped.items()):
                    children.append(
                        self._build_node(
                            members,
                            path=f"{node_id}_{label}",
                            depth=depth + 1,
                        )
                    )
        return ClusterTreeNode(
            id=node_id,
            name="",
            position=Position(x=0.0, z=0.0),
            height=1,
            chunk_ids=chunk_ids,
            children=children,
        )

    def _should_recurse(self, chunks: list[EnrichedChunk]) -> bool:
        return (
            len(chunks) > MAX_LEAF_CHUNKS
            and self._mean_pairwise_cosine(chunks) <= COHERENCE_STOP_THRESHOLD
        )

    def _hdbscan_labels(self, chunks: list[EnrichedChunk]) -> np.ndarray:
        if len(chunks) < MIN_CLUSTER_SIZE:
            return np.full(len(chunks), -1, dtype=np.int32)
        embeddings = np.asarray([item.embedding for item in chunks], dtype=np.float32)
        model = HDBSCAN(
            min_cluster_size=MIN_CLUSTER_SIZE,
            min_samples=MIN_SAMPLES,
            copy=False,
        )
        return np.asarray(model.fit_predict(embeddings), dtype=np.int32)

    def _groups_from_labels(
        self,
        labels: np.ndarray,
        chunks: list[EnrichedChunk],
    ) -> dict[str, list[EnrichedChunk]]:
        groups: dict[str, list[EnrichedChunk]] = defaultdict(list)
        noise: list[EnrichedChunk] = []
        for item, raw_label in zip(chunks, labels, strict=True):
            label = int(raw_label)
            if label == -1:
                noise.append(item)
            else:
                groups[f"cluster_{label}"].append(item)

        if noise:
            if groups:
                centroids = {
                    key: self._normalized_centroid(members)
                    for key, members in groups.items()
                    if members
                }
                unassigned: list[EnrichedChunk] = []
                for item in noise:
                    vector = self._normalized_vector(item.embedding)
                    best_key, best_sim = max(
                        (
                            (key, float(vector @ centroid))
                            for key, centroid in centroids.items()
                        ),
                        key=lambda pair: pair[1],
                    )
                    if best_sim > NOISE_ABSORPTION_THRESHOLD:
                        groups[best_key].append(item)
                    else:
                        logger.info(
                            "terrain: chunk %s remains unassigned after HDBSCAN noise absorption (best %.3f)",
                            item.chunk.id,
                            best_sim,
                        )
                        unassigned.append(item)
                if unassigned:
                    groups["cluster_unassigned"].extend(unassigned)
            else:
                for item in noise:
                    logger.info(
                        "terrain: chunk %s unassigned because HDBSCAN found no clusters",
                        item.chunk.id,
                    )
                groups["cluster_unassigned"].extend(noise)

        return {
            key: value
            for key, value in groups.items()
            if value
        }

    def _mean_pairwise_cosine(self, chunks: list[EnrichedChunk]) -> float:
        if len(chunks) < 2:
            return 1.0
        matrix = np.asarray([item.embedding for item in chunks], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        normalized = matrix / np.maximum(norms, 1e-8)
        sim = normalized @ normalized.T
        n = sim.shape[0]
        return float((sim.sum() - n) / max(n * (n - 1), 1))

    def _normalized_centroid(self, chunks: list[EnrichedChunk]) -> np.ndarray:
        matrix = np.asarray([item.embedding for item in chunks], dtype=np.float32)
        centroid = matrix.mean(axis=0)
        return self._normalized_vector(centroid)

    def _normalized_vector(self, vector: list[float] | np.ndarray) -> np.ndarray:
        arr = np.asarray(vector, dtype=np.float32)
        return arr / max(float(np.linalg.norm(arr)), 1e-8)

    def _node_id(self, path: str, chunks: list[EnrichedChunk]) -> str:
        return self._node_id_from_ids(path, [item.chunk.id for item in chunks])

    def _node_id_from_ids(self, path: str, chunk_ids: list[str]) -> str:
        chunk_part = "|".join(sorted(chunk_ids))
        return f"node_{short_hash(f'{path}|{chunk_part}', 16)}"
