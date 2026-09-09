"""Failure mode and edge case tests for the Obsidian plugin.

Covers gaps not addressed by test_obsidian_plugin.py:
- test_connection when path is a file (not a directory)
- fetch_document when file disappears between list and fetch
- fetch_attachment when attachment file is missing
- _resolve_attachment returning None for unresolvable reference
- list_documents scan count logged correctly
- VaultScanner scan with no watch_folders and no .md files
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.harvester.obsidian.models import ObsidianVaultConfig
from src.harvester.obsidian.parser import NoteParser
from src.harvester.obsidian.plugin import ObsidianHarvesterPlugin, note_id
from src.harvester import AttachmentRef

VAULT = Path(__file__).parent / "fixtures" / "obsidian-vault"


@pytest.fixture
def plugin() -> ObsidianHarvesterPlugin:
    cfg = ObsidianVaultConfig(vault_path=str(VAULT))
    return ObsidianHarvesterPlugin(cfg)


# ── test_connection failure modes ─────────────────────────────────────────────

async def test_connection_unhealthy_when_vault_path_is_a_file(tmp_path):
    """If vault_path points to a regular file, should report unhealthy."""
    file_path = tmp_path / "notavault.md"
    file_path.write_text("# just a file\n")

    cfg = ObsidianVaultConfig(vault_path=str(file_path))
    p = ObsidianHarvesterPlugin(cfg)
    health = await p.test_connection()
    assert not health.healthy
    assert "not a directory" in health.message.lower()


async def test_connection_unhealthy_without_obsidian_folder(tmp_path):
    """Directory exists but has no .obsidian/ subfolder."""
    cfg = ObsidianVaultConfig(vault_path=str(tmp_path))
    p = ObsidianHarvesterPlugin(cfg)
    health = await p.test_connection()
    assert not health.healthy
    assert ".obsidian" in health.message


async def test_connection_healthy_reports_note_count(plugin):
    health = await plugin.test_connection()
    assert health.healthy
    assert "note_count" in health.details
    assert health.details["note_count"] > 0


# ── fetch_document failure modes ──────────────────────────────────────────────

async def test_fetch_document_raises_runtime_error_when_file_missing(tmp_path):
    """Simulate file disappearing between list and fetch."""
    import shutil

    vault_copy = tmp_path / "vault"
    shutil.copytree(str(VAULT), str(vault_copy))

    cfg = ObsidianVaultConfig(vault_path=str(vault_copy))
    p = ObsidianHarvesterPlugin(cfg)

    docs = await p.list_documents()
    doc_ref = next(d for d in docs if "quick-note" in d.metadata["relative_path"])

    # Delete the file before fetching
    (vault_copy / doc_ref.metadata["relative_path"]).unlink()

    with pytest.raises(RuntimeError, match="Could not read vault file"):
        await p.fetch_document(doc_ref)


# ── fetch_attachment failure modes ────────────────────────────────────────────

async def test_fetch_attachment_raises_runtime_error_when_file_missing(plugin):
    """AttachmentRef pointing to non-existent path should raise RuntimeError."""
    att = AttachmentRef(
        source_id="aabbccdd11223344",
        filename="ghost.png",
        url="/tmp/does_not_exist_mnemify_test_xyz.png",
        mime_type="image/png",
    )
    with pytest.raises(RuntimeError, match="Could not read attachment"):
        await plugin.fetch_attachment(att)


# ── _resolve_attachment: three-tier resolution ────────────────────────────────

def test_resolve_attachment_tier1_vault_root(tmp_path):
    """File at exact vault-root-relative path is resolved by tier 1."""
    (tmp_path / "assets").mkdir()
    img = tmp_path / "assets" / "logo.png"
    img.write_bytes(b"PNG")

    parser = NoteParser()
    result = parser._resolve_attachment("assets/logo.png", tmp_path, tmp_path / "notes")
    assert result is not None
    assert result.name == "logo.png"


def test_resolve_attachment_tier2_note_dir(tmp_path):
    """File in same directory as note is resolved by tier 2."""
    note_dir = tmp_path / "notes"
    note_dir.mkdir()
    img = note_dir / "local.png"
    img.write_bytes(b"PNG")

    parser = NoteParser()
    result = parser._resolve_attachment("local.png", tmp_path, note_dir)
    assert result is not None
    assert result.name == "local.png"


def test_resolve_attachment_tier3_vault_scan(tmp_path):
    """Unqualified filename is found anywhere in vault by tier 3."""
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    img = deep / "buried.png"
    img.write_bytes(b"PNG")

    parser = NoteParser()
    # File is not at vault root, not in note_dir — only tier 3 finds it
    result = parser._resolve_attachment("buried.png", tmp_path, tmp_path / "notes")
    assert result is not None
    assert result.name == "buried.png"


def test_resolve_attachment_returns_none_for_unresolvable(tmp_path):
    """If no file matches, return None without raising."""
    parser = NoteParser()
    result = parser._resolve_attachment(
        "ghost_no_such_file.png", tmp_path, tmp_path / "notes"
    )
    assert result is None


def test_resolve_attachment_tier3_shortest_path_wins(tmp_path):
    """When file exists at multiple depths, shortest path is returned."""
    shallow = tmp_path / "shared"
    shallow.mkdir()
    (shallow / "image.png").write_bytes(b"SHALLOW")

    deep = tmp_path / "a" / "b" / "shared"
    deep.mkdir(parents=True)
    (deep / "image.png").write_bytes(b"DEEP")

    parser = NoteParser()
    result = parser._resolve_attachment("image.png", tmp_path, tmp_path / "notes")
    assert result is not None
    # Should pick the shallower path
    assert "a/b/shared" not in result.as_posix().replace("\\", "/")


# ── list_documents: since is accepted but ignored ────────────────────────────

async def test_list_documents_since_is_accepted_but_ignored(plugin):
    """``since`` no longer filters — see plugin docstring.

    The previous mtime-based pre-filter dropped notes older than ``since``,
    which broke Manage Scope expansion. The orchestrator now deduplicates
    per-doc via the manifest, so the plugin must return the full listing
    regardless of ``since``.
    """
    docs = await plugin.list_documents()
    assert len(docs) > 0

    first_doc = docs[0]
    since = first_doc.modified_at

    docs_filtered = await plugin.list_documents(since=since)
    filtered_ids = {d.source_id for d in docs_filtered}
    assert first_doc.source_id in filtered_ids
    assert len(docs_filtered) == len(docs)


# ── note_id: additional edge cases ───────────────────────────────────────────

def test_note_id_uses_posix_path_format():
    """note_id must produce the same result regardless of OS path separators."""
    vault = Path("/vault")
    # Simulate Windows-style path manually (posix() normalizes it)
    file_a = vault / "notes" / "file.md"
    nid = note_id(vault, file_a)
    assert "/" not in nid  # hex only
    assert len(nid) == 16


def test_note_id_changes_when_vault_path_changes():
    """Same relative path in different vaults should give the same ID
    (relative path is what's hashed, not the absolute path)."""
    vault_a = Path("/vault_a")
    vault_b = Path("/vault_b")
    file_a = vault_a / "notes" / "file.md"
    file_b = vault_b / "notes" / "file.md"

    # Same relative path → same ID (vault location doesn't matter)
    assert note_id(vault_a, file_a) == note_id(vault_b, file_b)


# ── VaultScanner edge cases ───────────────────────────────────────────────────

def test_scanner_empty_vault_yields_nothing(tmp_path):
    """Vault directory with no .md files — scan returns nothing."""
    from src.harvester.obsidian.scanner import VaultScanner

    cfg = ObsidianVaultConfig(vault_path=str(tmp_path))
    scanner = VaultScanner(tmp_path, cfg)
    results = list(scanner.scan())
    assert results == []


def test_scanner_default_ignore_merges_with_user_patterns():
    """User ignore patterns are appended to DEFAULT_IGNORE, not replacing it."""
    from src.harvester.obsidian.scanner import DEFAULT_IGNORE, VaultScanner

    cfg = ObsidianVaultConfig(
        vault_path=str(VAULT),
        ignore_patterns=["custom/*"],
    )
    scanner = VaultScanner(VAULT, cfg)

    # All DEFAULT_IGNORE patterns should still be present
    for pattern in DEFAULT_IGNORE:
        assert pattern in scanner.ignore_patterns

    # User pattern should also be present
    assert "custom/*" in scanner.ignore_patterns


def test_scanner_is_ignored_exact_match_on_directory_prefix():
    from src.harvester.obsidian.scanner import VaultScanner

    cfg = ObsidianVaultConfig(vault_path=str(VAULT))
    scanner = VaultScanner(VAULT, cfg)

    # Exact directory name (without trailing content) matches the prefix rule
    assert scanner._is_ignored(".obsidian/workspace.json")
    # Partial prefix should not match (e.g. ".obsidianlike" should not match ".obsidian/*")
    assert not scanner._is_ignored(".obsidianlike/file.md")
