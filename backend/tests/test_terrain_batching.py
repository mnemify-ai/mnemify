"""Tests for batched feature extraction + batched embeddings.

The batch path must be SAFE before it is fast: results are mapped back to each
chunk by an echoed id (never by position), a model that drops/reorders/duplicates
items must not silently misassign features, and a single bad chunk must not sink
its batch-mates. These tests pin that behavior with stubbed model clients (no
network).
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from src.terrain.agents.openai_clients import (
    OpenAIChunkFeatures,
    OpenAIChunkFeaturesBatch,
    OpenAIChunkFeaturesItem,
    OpenAIEmbeddingClient,
    OpenAIFeatureExtractor,
    OpenAISignal,
)
from src.terrain.utils.models import TerrainChunk


def _chunk(cid: int) -> TerrainChunk:
    # The stable id (cid) is embedded in the content so the stub can echo it
    # back inside the features it returns — letting the test assert each result
    # landed on the right chunk regardless of batch-local ordering.
    return TerrainChunk(
        id=f"c{cid}",
        doc_id=f"doc-{cid}",
        source_type="notion",
        source_id=f"s{cid}",
        doc_title=f"Doc {cid}",
        content=f"CID={cid} some body text",
        content_hash=f"hash-{cid}",
    )


def _model(cls, cid: int, **extra):
    return cls(
        summary=f"CID={cid}",
        products=[],
        customers=[],
        entities=[],
        tags=["t"],
        tag_type_hint="concept",
        theme="Theme",
        subtopic="Subtopic",
        confidence=0.9,
        **extra,
    )


class _Stub:
    """Stands in for ``extractor._client()``; fulfils ``.responses.parse``."""

    def __init__(self, *, batch_mode: str = "ok", fail_single_cids=()):
        self.batch_mode = batch_mode
        self.fail_single_cids = set(fail_single_cids)
        self.batch_calls = 0
        self.single_calls = 0
        self.responses = self

    def parse(self, *, model, input, text_format):  # noqa: A002
        user = next(m["content"] for m in input if m["role"] == "user")
        if text_format is OpenAIChunkFeaturesBatch:
            self.batch_calls += 1
            return self._batch(user)
        self.single_calls += 1
        cid = int(re.search(r"CID=(\d+)", user).group(1))
        if cid in self.fail_single_cids:
            raise ValueError(f"simulated single failure for {cid}")
        return SimpleNamespace(output_parsed=_model(OpenAIChunkFeatures, cid))

    def _batch(self, user: str):
        # Parse "=== CHUNK id=<local> ===\n...CID=<stable>..." blocks.
        blocks = re.split(r"=== CHUNK id=(\d+) ===", user)
        pairs = []
        for k in range(1, len(blocks), 2):
            local = int(blocks[k])
            cid = int(re.search(r"CID=(\d+)", blocks[k + 1]).group(1))
            pairs.append((local, cid))

        if self.batch_mode == "raise":
            raise ValueError("simulated batch failure")

        items = [_model(OpenAIChunkFeaturesItem, cid, id=local) for local, cid in pairs]
        if self.batch_mode == "reordered":
            items = list(reversed(items))
        elif self.batch_mode == "drop_one" and items:
            items = items[:-1]
        elif self.batch_mode == "duplicate" and items:
            items = [items[0], *items]
        return SimpleNamespace(output_parsed=OpenAIChunkFeaturesBatch(items=items))


def _extractor(stub: _Stub) -> OpenAIFeatureExtractor:
    ex = OpenAIFeatureExtractor(model="stub")
    ex._client = lambda: stub  # type: ignore[method-assign]
    return ex


def _cids(results) -> list:
    return [None if f is None else int(re.search(r"CID=(\d+)", f.summary).group(1)) for f in results]


def test_batch_happy_path_maps_each_chunk_to_its_own_features():
    stub = _Stub(batch_mode="ok")
    chunks = [_chunk(i) for i in range(4)]
    results = _extractor(stub).extract_batch(chunks)
    assert _cids(results) == [0, 1, 2, 3]
    assert stub.batch_calls == 1 and stub.single_calls == 0


def test_reordered_items_are_remapped_by_id_not_position():
    # The model returns items in reverse order; mapping by echoed id must still
    # align result[j] with chunks[j] (position-based mapping would corrupt this).
    stub = _Stub(batch_mode="reordered")
    chunks = [_chunk(i) for i in range(4)]
    results = _extractor(stub).extract_batch(chunks)
    assert _cids(results) == [0, 1, 2, 3]
    assert stub.batch_calls == 1


def test_dropped_id_triggers_split_retry_no_misassignment():
    # A batch that always drops one item can never satisfy the id check, so it
    # bisects all the way to singles — every chunk still gets ITS features.
    stub = _Stub(batch_mode="drop_one")
    chunks = [_chunk(i) for i in range(4)]
    results = _extractor(stub).extract_batch(chunks)
    assert _cids(results) == [0, 1, 2, 3]
    assert stub.single_calls == 4  # fell back to per-chunk
    assert stub.batch_calls >= 1


def test_duplicate_id_triggers_split_retry():
    stub = _Stub(batch_mode="duplicate")
    chunks = [_chunk(i) for i in range(4)]
    results = _extractor(stub).extract_batch(chunks)
    assert _cids(results) == [0, 1, 2, 3]
    assert stub.single_calls == 4


def test_single_bad_item_falls_back_to_none_others_survive():
    # Batch always raises → bisect to singles; only cid=2's single extract fails,
    # so it becomes None while its batch-mates extract cleanly.
    stub = _Stub(batch_mode="raise", fail_single_cids={2})
    chunks = [_chunk(i) for i in range(4)]
    results = _extractor(stub).extract_batch(chunks)
    assert _cids(results) == [0, 1, None, 3]


def test_fatal_error_propagates_not_swallowed():
    class _AuthBoom(_Stub):
        def parse(self, *, model, input, text_format):  # noqa: A002
            raise type("AuthenticationError", (Exception,), {})("bad key")

    import pytest

    chunks = [_chunk(i) for i in range(4)]
    with pytest.raises(Exception) as exc:
        _extractor(_AuthBoom()).extract_batch(chunks)
    assert type(exc.value).__name__ == "AuthenticationError"


def test_batch_matches_single_extract_for_same_chunk():
    # Cache parity: features built via the batch path must equal those built via
    # the single-item path for the same chunk (same _to_features mapping), so
    # existing content_hash cache entries stay valid.
    stub = _Stub(batch_mode="ok")
    ex = _extractor(stub)
    chunk = _chunk(7)
    (batched,) = ex.extract_batch([chunk, _chunk(8)])[:1]
    single = ex.extract(chunk)
    assert batched == single


def test_signals_are_mapped_from_openai_schema_and_severity_is_clamped():
    # A model-returned severity outside 0-100 must be clamped before it hits
    # ChunkSignalDraft (which enforces ge=0, le=100) — otherwise a slightly
    # out-of-spec LLM response would raise instead of just extracting.
    draft = OpenAISignal(
        kind="risk",
        title="Legal sign-off delay",
        summary="Legal sign-off delay could block the customer contract.",
        severity=150,
        status="open",
        owner="Erekle",
    )
    parsed = _model(OpenAIChunkFeatures, 0, signals=[draft])
    features = _extractor(_Stub())._to_features(parsed)

    assert len(features.signals) == 1
    got = features.signals[0]
    assert got.kind == "risk"
    assert got.owner == "Erekle"
    assert got.status == "open"
    assert got.severity == 100


def test_empty_and_singleton_batches():
    stub = _Stub(batch_mode="ok")
    ex = _extractor(stub)
    assert ex.extract_batch([]) == []
    # A singleton routes straight through the single path (no batch call).
    results = ex.extract_batch([_chunk(0)])
    assert _cids(results) == [0]
    assert stub.batch_calls == 0 and stub.single_calls == 1


# ── Batched embeddings ──────────────────────────────────────────────


class _EmbData:
    def __init__(self, index, embedding):
        self.index = index
        self.embedding = embedding


def test_embed_batch_preserves_order_even_if_api_reorders():
    client = OpenAIEmbeddingClient(model="stub")

    class _Emb:
        def create(self, **params):
            n = len(params["input"])
            # Return rows shuffled; embed_batch must re-sort by .index.
            data = [_EmbData(i, [float(i)]) for i in range(n)]
            return SimpleNamespace(data=list(reversed(data)))

    client._client = lambda: SimpleNamespace(embeddings=_Emb())  # type: ignore[method-assign]
    out = client.embed_batch(["a", "b", "c"])
    assert out == [[0.0], [1.0], [2.0]]


def test_embed_batch_empty_returns_empty():
    client = OpenAIEmbeddingClient(model="stub")
    assert client.embed_batch([]) == []
