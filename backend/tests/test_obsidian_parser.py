"""Tests for the Obsidian markdown parser (NoteParser).

Tests frontmatter extraction, plain-text stripping, and attachment
discovery against synthetic strings and fixture vault files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.harvester.obsidian.parser import NoteParser

VAULT = Path(__file__).parent / "fixtures" / "obsidian-vault"


@pytest.fixture
def parser() -> NoteParser:
    return NoteParser()


# ── 1. peek_frontmatter ────────────────────────────────────────────

def test_peek_frontmatter_extracts_title_and_tags(parser):
    title, meta = parser.peek_frontmatter(VAULT / "00-inbox" / "web-clip.md")
    assert title == "Interesting Article About Knowledge Graphs"
    assert "reading" in meta.get("tags", [])
    assert "knowledge-management" in meta.get("tags", [])


def test_peek_frontmatter_no_frontmatter_returns_none_title(parser):
    title, meta = parser.peek_frontmatter(VAULT / "00-inbox" / "quick-note.md")
    assert title is None
    assert meta == {}


def test_peek_frontmatter_normalises_string_tags(parser, tmp_path):
    """Tags written as comma-separated string should be normalised to a list."""
    note = tmp_path / "test.md"
    note.write_text("---\ntitle: Test\ntags: one, two, three\n---\nBody")
    title, meta = parser.peek_frontmatter(note)
    assert meta["tags"] == ["one", "two", "three"]


def test_peek_frontmatter_handles_missing_file(parser, tmp_path):
    title, meta = parser.peek_frontmatter(tmp_path / "nonexistent.md")
    assert title is None
    assert meta == {}


def test_peek_frontmatter_mnemify_generated_flag(parser):
    title, meta = parser.peek_frontmatter(VAULT / "02-wiki" / "compiled-output.md")
    assert meta.get("mnemify_generated") is True


# ── 2. strip_frontmatter ───────────────────────────────────────────

def test_strip_frontmatter_removes_yaml_block(parser):
    content = "---\ntitle: Hello\n---\n\nBody text here."
    result = parser.strip_frontmatter(content)
    assert result == "Body text here."


def test_strip_frontmatter_no_frontmatter_returns_unchanged(parser):
    content = "# Just a heading\n\nNo frontmatter here."
    assert parser.strip_frontmatter(content) == content


def test_strip_frontmatter_unclosed_delimiter_returns_unchanged(parser):
    """If there's no closing ---, treat the whole thing as body."""
    content = "---\ntitle: Oops\nBody without closing delimiter."
    assert parser.strip_frontmatter(content) == content


def test_strip_frontmatter_strips_leading_blank_lines(parser):
    content = "---\ntitle: Test\n---\n\n\nActual body."
    result = parser.strip_frontmatter(content)
    assert result == "Actual body."


# ── 3. find_attachments ────────────────────────────────────────────

def test_find_attachments_discovers_diagram_png(parser):
    """q2-planning.md has ![[diagram.png]] which should resolve."""
    note_path = VAULT / "meetings" / "q2-planning.md"
    content = note_path.read_text()
    refs = parser.find_attachments(content, VAULT, note_path.parent)

    filenames = {r.filename for r in refs}
    assert "diagram.png" in filenames


def test_find_attachments_resolves_via_vault_scan(parser):
    """project-mnemify.md references diagram.png — resolves by shortest path."""
    note_path = VAULT / "notes" / "project-mnemify.md"
    content = note_path.read_text()
    refs = parser.find_attachments(content, VAULT, note_path.parent)

    filenames = {r.filename for r in refs}
    assert "diagram.png" in filenames


def test_find_attachments_no_embeds_returns_empty(parser):
    note_path = VAULT / "00-inbox" / "quick-note.md"
    content = note_path.read_text()
    refs = parser.find_attachments(content, VAULT, note_path.parent)
    # quick-note.md has no ![[...]] embeds
    assert refs == []


def test_find_attachments_deduplicates_same_file(parser, tmp_path):
    """Same attachment referenced twice should appear only once."""
    content = "![[diagram.png]]\n\nSome text\n\n![[diagram.png]]"
    refs = parser.find_attachments(content, VAULT, VAULT / "notes")
    assert len(refs) == 1


def test_find_attachments_ignores_md_wikilinks(parser, tmp_path):
    """Wikilinks to .md files are not attachments."""
    content = "[[other-note]] and ![[other-note.md]]"
    refs = parser.find_attachments(content, VAULT, VAULT)
    # .md is not in ATTACHMENT_EXTENSIONS
    assert refs == []


def test_find_attachments_strips_display_alias(parser):
    """![[diagram.png|My Diagram]] should resolve to diagram.png."""
    content = "![[diagram.png|My Diagram]]"
    refs = parser.find_attachments(content, VAULT, VAULT / "notes")
    filenames = {r.filename for r in refs}
    assert "diagram.png" in filenames


def test_find_attachments_sets_mime_type(parser):
    content = "![[diagram.png]]"
    refs = parser.find_attachments(content, VAULT, VAULT / "notes")
    if refs:
        assert refs[0].mime_type == "image/png"


def test_find_attachments_source_id_is_hex(parser):
    content = "![[diagram.png]]"
    refs = parser.find_attachments(content, VAULT, VAULT / "notes")
    if refs:
        assert len(refs[0].source_id) == 16
        assert all(c in "0123456789abcdef" for c in refs[0].source_id)


# ── embeds must stay inside the vault ─────────────────────────────────

def _vault_with_secret_outside(tmp_path):
    vault = tmp_path / "vault"
    (vault / "notes").mkdir(parents=True)
    (vault / "inside.pdf").write_bytes(b"%PDF")
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF secret")
    return vault, outside


def test_absolute_embed_is_ignored(parser, tmp_path):
    vault, outside = _vault_with_secret_outside(tmp_path)
    refs = parser.find_attachments(f"![[{outside}]]", vault, vault / "notes")
    assert refs == []


def test_dotdot_embed_is_ignored(parser, tmp_path):
    vault, _ = _vault_with_secret_outside(tmp_path)
    refs = parser.find_attachments("![[../outside.pdf]]", vault, vault / "notes")
    assert refs == []
    refs = parser.find_attachments("![[../../outside.pdf]]", vault, vault / "notes")
    assert refs == []


def test_symlink_escaping_the_vault_is_ignored(parser, tmp_path):
    vault, outside = _vault_with_secret_outside(tmp_path)
    link = vault / "link.pdf"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported here")
    assert parser.find_attachments("![[link.pdf]]", vault, vault) == []
    # tier-3 name scan would also find it — still refused
    assert parser.find_attachments("![[sub/link.pdf]]", vault, vault) == []


def test_embed_inside_the_vault_still_resolves(parser, tmp_path):
    vault, _ = _vault_with_secret_outside(tmp_path)
    refs = parser.find_attachments("![[inside.pdf]] and ![[../inside.pdf]]", vault, vault / "notes")
    assert {r.filename for r in refs} == {"inside.pdf"}
