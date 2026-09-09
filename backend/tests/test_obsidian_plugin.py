"""Tests for ObsidianHarvesterPlugin — SourcePlugin contract compliance.

All tests run against the fixture vault.  No network, no running Obsidian.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.harvester import DocRef, HealthStatus, RawDocument, SourcePlugin
from src.harvester.obsidian.models import ObsidianVaultConfig
from src.harvester.obsidian.plugin import ObsidianHarvesterPlugin, note_id

VAULT = Path(__file__).parent / "fixtures" / "obsidian-vault"


@pytest.fixture
def plugin() -> ObsidianHarvesterPlugin:
    cfg = ObsidianVaultConfig(
        vault_path=str(VAULT),
        watch_folders=[],
        ignore_patterns=["templates/*", "02-wiki/*"],
    )
    return ObsidianHarvesterPlugin(cfg)


# ── 1. SourcePlugin contract ───────────────────────────────────────

def test_plugin_is_source_plugin_subclass():
    assert issubclass(ObsidianHarvesterPlugin, SourcePlugin)


def test_plugin_implements_all_abstract_methods():
    """Instantiating the plugin should succeed without TypeError."""
    cfg = ObsidianVaultConfig(vault_path=str(VAULT))
    p = ObsidianHarvesterPlugin(cfg)
    assert p is not None


# ── 2. test_connection ────────────────────────────────────────────

async def test_connection_healthy_for_valid_vault(plugin):
    health = await plugin.test_connection()
    assert isinstance(health, HealthStatus)
    assert health.healthy
    assert health.source_type == "obsidian"
    assert "Vault OK" in health.message
    assert health.details.get("note_count", 0) > 0


async def test_connection_unhealthy_for_nonexistent_path():
    cfg = ObsidianVaultConfig(vault_path="/tmp/nonexistent-vault-xyz")
    p = ObsidianHarvesterPlugin(cfg)
    health = await p.test_connection()
    assert not health.healthy
    assert "not found" in health.message.lower()


async def test_connection_unhealthy_for_path_without_obsidian_folder(tmp_path):
    cfg = ObsidianVaultConfig(vault_path=str(tmp_path))
    p = ObsidianHarvesterPlugin(cfg)
    health = await p.test_connection()
    assert not health.healthy
    assert ".obsidian" in health.message


# ── 3. list_documents ─────────────────────────────────────────────

async def test_list_documents_returns_doc_refs(plugin):
    docs = await plugin.list_documents()
    assert len(docs) > 0
    for doc in docs:
        assert isinstance(doc, DocRef)
        assert doc.source_type == "obsidian"
        assert doc.source_id
        assert doc.title
        assert doc.modified_at is not None


async def test_list_documents_populates_required_metadata(plugin):
    docs = await plugin.list_documents()
    for doc in docs:
        assert "document_type" in doc.metadata
        assert doc.metadata["document_type"] == "note"
        assert "relative_path" in doc.metadata
        assert "folder" in doc.metadata
        assert "tags" in doc.metadata
        assert isinstance(doc.metadata["tags"], list)


async def test_list_documents_excludes_templates_and_wiki(plugin):
    """plugin has ignore_patterns=["templates/*", "02-wiki/*"]."""
    docs = await plugin.list_documents()
    paths = {d.metadata["relative_path"] for d in docs}
    assert not any(p.startswith("templates/") for p in paths)
    assert not any(p.startswith("02-wiki/") for p in paths)


async def test_list_documents_includes_nested_notes(plugin):
    docs = await plugin.list_documents()
    paths = {d.metadata["relative_path"] for d in docs}
    assert "notes/nested/deep-note.md" in paths


async def test_list_documents_title_fallback_to_stem(plugin):
    """quick-note.md has no frontmatter title; should fall back to filename stem."""
    docs = await plugin.list_documents()
    doc = next(d for d in docs if "quick-note" in d.metadata["relative_path"])
    assert doc.title == "quick-note"


async def test_list_documents_title_from_frontmatter(plugin):
    """web-clip.md has a frontmatter title."""
    docs = await plugin.list_documents()
    doc = next(d for d in docs if "web-clip" in d.metadata["relative_path"])
    assert doc.title == "Interesting Article About Knowledge Graphs"


async def test_list_documents_source_url_is_obsidian_protocol(plugin):
    docs = await plugin.list_documents()
    for doc in docs:
        assert doc.source_url is not None
        assert doc.source_url.startswith("obsidian://")


async def test_list_documents_ignores_since(plugin, tmp_path):
    """``since`` is accepted for interface compatibility but no longer filters.

    Previously a mtime-based pre-filter dropped notes older than ``since``,
    which broke Manage Scope expansion (notes in a newly-watched folder are
    long-untouched, so they'd be filtered out before the orchestrator's
    per-doc Layer 1 short-circuit could see them). The orchestrator now
    deduplicates per-doc; the plugin must return the full in-scope listing
    regardless of ``since``.
    """
    from datetime import datetime, timezone

    far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    docs_filtered = await plugin.list_documents(since=far_future)
    docs_unfiltered = await plugin.list_documents(since=None)
    assert len(docs_filtered) == len(docs_unfiltered) > 0


async def test_list_documents_since_none_returns_all(plugin):
    docs = await plugin.list_documents(since=None)
    assert len(docs) > 0


# ── 4. fetch_document ─────────────────────────────────────────────

async def test_fetch_document_returns_raw_document(plugin):
    docs = await plugin.list_documents()
    doc_ref = docs[0]
    raw = await plugin.fetch_document(doc_ref)
    assert isinstance(raw, RawDocument)
    assert raw.format == "md"
    assert raw.source_id == doc_ref.source_id
    assert len(raw.content) > 0


async def test_fetch_document_content_is_markdown(plugin):
    docs = await plugin.list_documents()
    # Find web-clip which has frontmatter
    doc_ref = next(d for d in docs if "web-clip" in d.metadata["relative_path"])
    raw = await plugin.fetch_document(doc_ref)
    text = raw.content.decode("utf-8")
    assert "---" in text  # frontmatter delimiter
    assert "Knowledge Graphs" in text


async def test_fetch_document_discovers_attachments(plugin):
    """q2-planning.md embeds diagram.png."""
    docs = await plugin.list_documents()
    doc_ref = next(d for d in docs if "q2-planning" in d.metadata["relative_path"])
    raw = await plugin.fetch_document(doc_ref)
    assert len(raw.attachments) > 0
    assert any(a.filename == "diagram.png" for a in raw.attachments)


async def test_fetch_document_metadata_includes_vault_name(plugin):
    docs = await plugin.list_documents()
    raw = await plugin.fetch_document(docs[0])
    assert "vault_name" in raw.metadata
    assert raw.metadata["vault_name"] == "obsidian-vault"


# ── 5. fetch_attachment ───────────────────────────────────────────

async def test_fetch_attachment_reads_local_file(plugin):
    """diagram.png should be readable as bytes."""
    docs = await plugin.list_documents()
    doc_ref = next(d for d in docs if "q2-planning" in d.metadata["relative_path"])
    raw = await plugin.fetch_document(doc_ref)

    att = next((a for a in raw.attachments if a.filename == "diagram.png"), None)
    assert att is not None

    att_bytes = await plugin.fetch_attachment(att)
    assert len(att_bytes) > 0
    # Verify it's a PNG by magic bytes
    assert att_bytes[:4] == b"\x89PNG"


# ── 7. note_id ────────────────────────────────────────────────────

def test_note_id_is_deterministic():
    vault = Path("/tmp/vault")
    file_a = vault / "notes" / "project.md"
    id1 = note_id(vault, file_a)
    id2 = note_id(vault, file_a)
    assert id1 == id2


def test_note_id_is_16_hex_chars():
    vault = Path("/tmp/vault")
    file_path = vault / "daily" / "2026-04-15.md"
    nid = note_id(vault, file_path)
    assert len(nid) == 16
    assert all(c in "0123456789abcdef" for c in nid)


def test_note_id_differs_for_different_paths():
    vault = Path("/tmp/vault")
    id_a = note_id(vault, vault / "notes" / "a.md")
    id_b = note_id(vault, vault / "notes" / "b.md")
    assert id_a != id_b


# ── 8. mark_harvested is a no-op (inherited default) ─────────────

async def test_mark_harvested_is_noop(plugin):
    """The ABC default should not raise."""
    await plugin.mark_harvested("some-id", "2026-04-15T00:00:00Z")


# ── 9. aclose is a no-op (inherited default) ─────────────────────

async def test_aclose_is_noop(plugin):
    await plugin.aclose()  # should not raise
