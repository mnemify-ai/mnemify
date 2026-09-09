"""Unit coverage for /api/ask raw-chunk expansion (ask_expansion.py)."""

from __future__ import annotations

from pathlib import Path

from src.api.ask_expansion import (
    PER_ITEM_CHUNK_CAP,
    expand_bundle,
)
from src.api.ask_retrieval import ContextItem
from src.terrain.utils.store import TerrainStore
from src.utils.hashing import short_hash


def _chunk_row(chunk_id: str, doc_id: str, content: str, title: str = "Doc"):
    from src.terrain.utils.models import TerrainChunk

    return TerrainChunk(
        id=chunk_id,
        doc_id=doc_id,
        source_type="notion",
        source_id="src-1",
        doc_title=title,
        heading_path=["Section"],
        content=content,
        content_hash=f"sha256:{chunk_id}",
    )


def _store_with(chunks) -> TerrainStore:
    store = TerrainStore(":memory:")
    store.upsert_chunks(chunks)
    return store


def _note_item(doc_id: str, citation_id: str = "c1", **kwargs) -> ContextItem:
    return ContextItem(
        citation_id=citation_id,
        node_id=f"n-{short_hash(doc_id, 8)}",
        node_type="note",
        layer=0,
        label="Note",
        summary="excerpt…",
        **kwargs,
    )


def test_note_expansion_via_doc_id_hash():
    """Old artifacts carry no sourceChunkIds on notes — the doc_id hash
    mapping must resolve them against the chunks table."""
    store = _store_with([
        _chunk_row("ch-1", "doc-a", "Full raw content of the workflow doc."),
    ])
    item = _note_item("doc-a")
    result = expand_bundle([item], store)
    assert result.expanded
    assert result.chunk_count == 1
    assert len(item.raw_excerpts) == 1
    assert "Full raw content" in item.raw_excerpts[0]
    assert "Doc > Section" in item.raw_excerpts[0]


def test_note_expansion_prefers_stamped_chunk_ids():
    store = _store_with([
        _chunk_row("ch-1", "doc-a", "stamped content"),
        _chunk_row("ch-2", "doc-b", "wrong doc"),
    ])
    item = _note_item("doc-a", source_chunk_ids=["ch-1"])
    result = expand_bundle([item], store)
    assert result.chunk_count == 1
    assert "stamped content" in item.raw_excerpts[0]


def test_signal_expansion_uses_source_chunk_ids():
    store = _store_with([_chunk_row("ch-9", "doc-x", "risk detail text")])
    item = ContextItem(
        citation_id="c1", node_id="signal.r1", node_type="signal", layer=2,
        label="Risk", summary="", source_chunk_ids=["ch-9"],
    )
    result = expand_bundle([item], store)
    assert result.expanded
    assert "risk detail text" in item.raw_excerpts[0]


def test_tags_and_regions_not_expanded():
    store = _store_with([_chunk_row("ch-1", "doc-a", "content")])
    tag = ContextItem(citation_id="c1", node_id="tag.x", node_type="tag",
                      layer=2, label="Tag", summary="compiled note",
                      source_chunk_ids=["ch-1"])
    result = expand_bundle([tag], store)
    assert not result.expanded
    assert tag.raw_excerpts == []


def test_per_item_chunk_cap():
    doc_id = "doc-many"
    chunks = [
        _chunk_row(f"ch-{i}", doc_id, f"chunk body {i}")
        for i in range(PER_ITEM_CHUNK_CAP + 3)
    ]
    store = _store_with(chunks)
    item = _note_item(doc_id)
    result = expand_bundle([item], store)
    assert result.chunk_count == PER_ITEM_CHUNK_CAP
    assert len(item.raw_excerpts) == PER_ITEM_CHUNK_CAP


def test_budget_truncates_across_items():
    store = _store_with([
        _chunk_row("ch-1", "doc-a", "A" * 500),
        _chunk_row("ch-2", "doc-b", "B" * 500),
    ])
    first = _note_item("doc-a", citation_id="c1")
    second = _note_item("doc-b", citation_id="c2")
    result = expand_bundle([first, second], store, budget_chars=600)
    # First item eats most of the budget; the second gets a truncated
    # excerpt or nothing, and total attached chars stay within budget.
    assert result.chars <= 600
    assert first.raw_excerpts
    total = sum(len(e) for e in first.raw_excerpts + second.raw_excerpts)
    assert total <= 600


def test_missing_db_is_noop(tmp_path):
    item = _note_item("doc-a")
    result = expand_bundle([item], None, db_path=tmp_path / "missing.db")
    assert not result.expanded
    assert item.raw_excerpts == []
