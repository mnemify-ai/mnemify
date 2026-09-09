from __future__ import annotations

import hashlib
import math
import os
import re
import threading

from src.terrain.utils.models import ChunkFeatures, TerrainChunk
from src.utils.hashing import sha256_hash
from src.terrain.agents.usage import ledger


class EmbeddingClient:
    _openai = None
    _client_lock = threading.Lock()

    def __init__(self, model: str = "text-embedding-3-large", dimensions: int | None = None):
        self.model = model
        self.dimensions = dimensions

    def embedding_text(
        self,
        features: ChunkFeatures,
        chunk: TerrainChunk | None = None,
    ) -> str:
        lines = [
            features.summary,
            "Product: " + " ".join(features.products * 4),
            "Customer: " + " ".join(features.customers * 3),
            "Topic: " + " ".join(features.entities + features.tags),
        ]
        if chunk is not None:
            if chunk.heading_path:
                lines.append("Path: " + " > ".join(chunk.heading_path))
            if chunk.wikilinks:
                # Repeat refs so reference-linked chunks pull together in
                # embedding space — same weighting pattern used for products
                # and customers above.
                lines.append("Refs: " + " ".join(chunk.wikilinks * 2))
            if chunk.frontmatter_tags:
                lines.append("Tags: " + " ".join(chunk.frontmatter_tags))
        return "\n".join(lines)

    def hash(self, text: str) -> str:
        return sha256_hash(f"{self.model}:{self.dimensions or 'default'}:{text}")

    def _client(self):
        if self._openai is not None:
            return self._openai
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for terrain embeddings.")
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "Install backend dependencies to use terrain OpenAI embeddings."
            ) from e

        with self._client_lock:
            if self._openai is None:
                self._openai = OpenAI()
        return self._openai

    def embed(self, text: str, dimensions: int | None = None) -> list[float]:
        params: dict[str, object] = {
            "model": self.model,
            "input": text,
            "encoding_format": "float",
        }
        requested_dimensions = dimensions if dimensions is not None else self.dimensions
        if requested_dimensions is not None:
            params["dimensions"] = requested_dimensions
        response = self._client().embeddings.create(**params)
        ledger.record_openai(getattr(response, "usage", None), model=self.model)
        return list(response.data[0].embedding)

    def embed_batch(
        self, texts: list[str], dimensions: int | None = None
    ) -> list[list[float]]:
        """Embed many texts in a single API round-trip. Order-preserving: the
        OpenAI embeddings endpoint accepts a list and returns one vector per
        input. Collapses ~one HTTP call per chunk into one per batch (the bulk
        of enrich's wall-time on a large vault). Returns vectors aligned 1:1 to
        ``texts``; we re-sort by ``data[i].index`` defensively rather than trust
        positional order."""
        if not texts:
            return []
        params: dict[str, object] = {
            "model": self.model,
            "input": texts,
            "encoding_format": "float",
        }
        requested_dimensions = dimensions if dimensions is not None else self.dimensions
        if requested_dimensions is not None:
            params["dimensions"] = requested_dimensions
        response = self._client().embeddings.create(**params)
        ledger.record_openai(getattr(response, "usage", None), model=self.model)
        ordered = sorted(response.data, key=lambda d: d.index)
        return [list(d.embedding) for d in ordered]


class LocalHashEmbeddingClient(EmbeddingClient):
    model = "local-hash-v1"

    def __init__(self, dimensions: int = 64):
        self.dimensions = dimensions

    def hash(self, text: str) -> str:
        return sha256_hash(f"{self.model}:{self.dimensions}:{text}")

    def embed(self, text: str, dimensions: int | None = None) -> list[float]:
        dimensions = dimensions or self.dimensions
        vector = [0.0] * dimensions
        tokens = re.findall(r"\b[a-zA-Z0-9][a-zA-Z0-9-]{2,}\b", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[idx] += sign
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [round(v / norm, 6) for v in vector]

    def embed_batch(
        self, texts: list[str], dimensions: int | None = None
    ) -> list[list[float]]:
        # No network for the local hash embedder — a plain loop keeps the batch
        # interface uniform across backends so the enrich path is mode-agnostic.
        return [self.embed(t, dimensions) for t in texts]
