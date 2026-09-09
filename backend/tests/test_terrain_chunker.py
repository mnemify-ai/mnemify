from __future__ import annotations

from src.terrain.preprocessing.chunker import MarkdownChunker
from src.terrain.utils.models import SourceDocument


def test_chunker_preserves_source_hierarchy_metadata():
    doc = SourceDocument(
        id="doc-1",
        source_type="confluence",
        source_id="page-1",
        title="Company Notes",
        source_url="https://example.test/page-1",
        metadata={
            "parent_id": "parent-1",
            "parent_title": "Customers",
            "ancestors": [
                {"id": "root", "title": "Document Analysis"},
                {"id": "parent-1", "title": "Customers"},
            ],
        },
        content="# ACME\n\nACME wants invoice extraction and table parsing.",
    )

    chunks = MarkdownChunker(min_words=1).chunk([doc])

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.source_parent_id == "parent-1"
    assert chunk.source_parent_title == "Customers"
    assert chunk.source_ancestor_ids == ["root", "parent-1"]
    assert chunk.source_breadcrumb_titles == ["Document Analysis", "Customers", "Company Notes"]
    assert chunk.heading_path == ["ACME"]


def test_chunker_splits_large_sections():
    text = "# Long\n\n" + " ".join(f"word{i}" for i in range(160))
    doc = SourceDocument(
        id="doc-1",
        source_type="notion",
        source_id="page-1",
        title="Long Page",
        content=text,
    )

    chunks = MarkdownChunker(min_words=1, target_words=60, max_words=100).chunk([doc])

    # A 160-word body with target_words=60 must be split into several chunks;
    # none exceeds max_words and they all carry the source doc id.
    assert len(chunks) >= 2
    assert all(chunk.doc_id == "doc-1" for chunk in chunks)
    assert all(len(chunk.content.split()) <= 100 for chunk in chunks)
