from __future__ import annotations

import math

import numpy as np

from src.terrain.utils.models import ClusterTreeNode, EnrichedChunk, Position
from src.terrain.utils.store import TerrainStore
from src.utils.hashing import short_hash


class TerrainLayout:
    def __init__(self, store: TerrainStore):
        self.store = store

    def semantic_positions(
        self,
        nodes: list[ClusterTreeNode],
        chunks_by_node: dict[str, list[EnrichedChunk]],
        radius: float = 120.0,
        persist: bool = True,
    ) -> dict[str, Position]:
        """Place nodes by preserving centroid embedding distances in 2D."""
        if not nodes:
            return {}

        if len(nodes) == 1:
            pos = Position(x=0.0, z=0.0)
            if persist:
                self.store.save_position(nodes[0].id, pos.x, pos.z)
            return {nodes[0].id: pos}

        ordered = sorted(nodes, key=lambda node: node.id)
        largest = max(
            ordered,
            key=lambda node: (len(chunks_by_node.get(node.id, [])), node.id),
        )
        embedding_dim = self._embedding_dim(chunks_by_node)
        centroids = [
            self._normalized_centroid(
                chunks_by_node.get(node.id, []),
                embedding_dim=embedding_dim,
            )
            for node in ordered
        ]
        coordinates = self._classical_mds(self._cosine_distance_matrix(centroids))

        largest_index = ordered.index(largest)
        coordinates = coordinates - coordinates[largest_index]
        coordinates = self._orient_coordinates(coordinates, largest_index)
        coordinates = self._scale_to_radius(coordinates, radius)

        out: dict[str, Position] = {}
        for node, coordinate in zip(ordered, coordinates, strict=True):
            x = 0.0 if node.id == largest.id else float(coordinate[0])
            z = 0.0 if node.id == largest.id else float(coordinate[1])
            pos = Position(x=round(x, 3), z=round(z, 3))
            if persist:
                self.store.save_position(node.id, pos.x, pos.z)
            out[node.id] = pos
        return out

    def positions(
        self,
        node_ids: list[str],
        radius: float = 120.0,
    ) -> dict[str, Position]:
        """Place ``node_ids`` deterministically on a disc of given radius.

        Positions persist in ``layout_seeds`` so subsequent builds reuse
        the same coordinates even when the set of inputs changes slightly.
        """
        ordered = sorted(node_ids)
        count = max(len(ordered), 1)
        out: dict[str, Position] = {}
        for index, node_id in enumerate(ordered):
            existing = self.store.get_position(node_id)
            if existing:
                out[node_id] = Position(x=existing[0], z=existing[1])
                continue
            angle = (2 * math.pi * index) / count + self._jitter(node_id)
            ring = radius * (0.45 + 0.45 * ((index % 3) / 2 if count > 3 else 0.4))
            x = round(math.cos(angle) * ring, 3)
            z = round(math.sin(angle) * ring, 3)
            self.store.save_position(node_id, x, z)
            out[node_id] = Position(x=x, z=z)
        return out

    def nested_positions(
        self,
        parent_id: str,
        child_ids: list[str],
        parent_position: Position,
        parent_radius: float,
        scale: float = 0.35,
        child_nodes: list[ClusterTreeNode] | None = None,
        chunks_by_node: dict[str, list[EnrichedChunk]] | None = None,
    ) -> dict[str, Position]:
        """Place ``child_ids`` inside the parent at ``parent_position``.

        ``parent_radius`` controls the local layout disc; ``scale`` shrinks
        the local positions when composing with the parent so children
        cluster near the parent's center rather than its edge. Default
        ``0.35`` matches the prior peak-in-region behavior.
        """
        if child_nodes is not None and chunks_by_node is not None:
            local = self.semantic_positions(
                child_nodes,
                chunks_by_node,
                radius=max(parent_radius, 8.0),
                persist=False,
            )
        else:
            local = self.positions(
                [f"{parent_id}:{cid}" for cid in child_ids],
                radius=max(parent_radius, 8.0),
            )
        out: dict[str, Position] = {}
        for cid in child_ids:
            lookup_id = cid if cid in local else f"{parent_id}:{cid}"
            pos = local[lookup_id]
            composed = Position(
                x=round(parent_position.x + pos.x * scale, 3),
                z=round(parent_position.z + pos.z * scale, 3),
            )
            self.store.save_position(cid, composed.x, composed.z)
            out[cid] = composed
        return out

    # Backwards-compatible alias for callers that still say peak_positions.
    peak_positions = nested_positions

    def _jitter(self, node_id: str) -> float:
        return int(short_hash(node_id, 4), 16) / 65535 * 0.4

    def _cosine_distance_matrix(self, vectors: list[np.ndarray]) -> np.ndarray:
        if not vectors:
            return np.zeros((0, 0), dtype=np.float32)
        matrix = np.asarray(vectors, dtype=np.float32)
        similarity = np.clip(matrix @ matrix.T, -1.0, 1.0)
        distance = 1.0 - similarity
        np.fill_diagonal(distance, 0.0)
        return distance

    def _classical_mds(self, distance: np.ndarray) -> np.ndarray:
        count = distance.shape[0]
        if count == 0:
            return np.zeros((0, 2), dtype=np.float32)
        if count == 1:
            return np.zeros((1, 2), dtype=np.float32)

        squared = distance.astype(np.float64) ** 2
        identity = np.eye(count)
        centering = identity - np.ones((count, count)) / count
        gram = -0.5 * centering @ squared @ centering
        eigenvalues, eigenvectors = np.linalg.eigh(gram)
        order = np.argsort(eigenvalues)[::-1]

        coordinates = np.zeros((count, 2), dtype=np.float64)
        dimensions = 0
        for index in order:
            value = float(eigenvalues[index])
            if value <= 1e-10:
                continue
            coordinates[:, dimensions] = eigenvectors[:, index] * math.sqrt(value)
            dimensions += 1
            if dimensions == 2:
                break
        return coordinates.astype(np.float32)

    def _orient_coordinates(self, coordinates: np.ndarray, anchor_index: int) -> np.ndarray:
        for index, coordinate in enumerate(coordinates):
            if index == anchor_index:
                continue
            if coordinate[0] < -1e-8 or (
                abs(float(coordinate[0])) <= 1e-8 and coordinate[1] < -1e-8
            ):
                return coordinates * -1.0
            break
        return coordinates

    def _scale_to_radius(self, coordinates: np.ndarray, radius: float) -> np.ndarray:
        max_distance = float(np.linalg.norm(coordinates, axis=1).max(initial=0.0))
        if max_distance <= 1e-8:
            return coordinates
        return coordinates * (radius / max_distance)

    def _embedding_dim(self, chunks_by_node: dict[str, list[EnrichedChunk]]) -> int:
        for chunks in chunks_by_node.values():
            for item in chunks:
                if item.embedding:
                    return len(item.embedding)
        return 1

    def _normalized_centroid(
        self,
        chunks: list[EnrichedChunk],
        *,
        embedding_dim: int,
    ) -> np.ndarray:
        if not chunks:
            return np.zeros(embedding_dim, dtype=np.float32)
        matrix = np.asarray([item.embedding for item in chunks], dtype=np.float32)
        centroid = matrix.mean(axis=0)
        return self._normalized_vector(centroid)

    def _normalized_vector(self, vector: list[float] | np.ndarray) -> np.ndarray:
        arr = np.asarray(vector, dtype=np.float32)
        return arr / max(float(np.linalg.norm(arr)), 1e-8)
