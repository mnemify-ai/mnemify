"""Tests for :func:`src.harvester.jira.adf.markdown_from_adf`.

One test per ADF node type in the mapping table, plus mark-composition,
nested lists, table with header, and regression gates.
"""

from __future__ import annotations

import pytest

from src.harvester.jira.adf import markdown_from_adf, text_from_adf


# ── Fixture helpers ──────────────────────────────────────────────────────────

def _text(value: str, marks=None) -> dict:
    node: dict = {"type": "text", "text": value}
    if marks is not None:
        node["marks"] = marks
    return node


def _paragraph(*children: dict) -> dict:
    return {"type": "paragraph", "content": list(children)}


def _heading(level: int, *children: dict) -> dict:
    return {"type": "heading", "attrs": {"level": level}, "content": list(children)}


def _list_item(*children: dict) -> dict:
    return {"type": "listItem", "content": list(children)}


def _bullet_list(*items: dict) -> dict:
    return {"type": "bulletList", "content": list(items)}


def _ordered_list(*items: dict) -> dict:
    return {"type": "orderedList", "content": list(items)}


def _code_block(*children: dict, language: str = "python") -> dict:
    return {
        "type": "codeBlock",
        "attrs": {"language": language},
        "content": list(children),
    }


def _doc(*children: dict) -> dict:
    return {"type": "doc", "content": list(children)}


def _blockquote(*children: dict) -> dict:
    return {"type": "blockquote", "content": list(children)}


def _table(*rows: dict) -> dict:
    return {"type": "table", "content": list(rows)}


def _table_row(*cells: dict) -> dict:
    return {"type": "tableRow", "content": list(cells)}


def _table_header(*children: dict) -> dict:
    return {"type": "tableHeader", "content": list(children)}


def _table_cell(*children: dict) -> dict:
    return {"type": "tableCell", "content": list(children)}


# ── None and empty input ─────────────────────────────────────────────────────

def test_none_returns_empty():
    assert markdown_from_adf(None) == ""


def test_empty_doc_returns_empty():
    assert markdown_from_adf(_doc()) == ""


# ── doc ──────────────────────────────────────────────────────────────────────

def test_doc_recurses_children():
    result = markdown_from_adf(_doc(
        _paragraph(_text("first")),
        _paragraph(_text("second")),
    ))
    assert "first" in result
    assert "second" in result


# ── paragraph ────────────────────────────────────────────────────────────────

def test_paragraph_inline_join_no_space_insertion():
    # Adjacent text nodes must concatenate without extra spaces.
    result = markdown_from_adf(_paragraph(_text("hello"), _text(" world")))
    assert result.strip() == "hello world"


def test_paragraph_adds_blank_line():
    result = markdown_from_adf(_doc(
        _paragraph(_text("A")),
        _paragraph(_text("B")),
    ))
    # There should be a blank line between the two paragraphs.
    assert "\n\n" in result


# ── text marks ───────────────────────────────────────────────────────────────

def test_mark_strong():
    result = markdown_from_adf(_paragraph(
        _text("bold", marks=[{"type": "strong"}])
    ))
    assert "**bold**" in result


def test_mark_em():
    result = markdown_from_adf(_paragraph(
        _text("ital", marks=[{"type": "em"}])
    ))
    assert "*ital*" in result


def test_mark_code():
    result = markdown_from_adf(_paragraph(
        _text("x = 1", marks=[{"type": "code"}])
    ))
    assert "`x = 1`" in result


def test_mark_link():
    result = markdown_from_adf(_paragraph(
        _text("click", marks=[{"type": "link", "attrs": {"href": "https://example.com"}}])
    ))
    assert "[click](https://example.com)" in result


def test_mark_strike():
    result = markdown_from_adf(_paragraph(
        _text("gone", marks=[{"type": "strike"}])
    ))
    assert "~~gone~~" in result


def test_mark_underline_pass_through():
    # Underline has no native markdown representation — text passes through.
    result = markdown_from_adf(_paragraph(
        _text("under", marks=[{"type": "underline"}])
    ))
    assert "under" in result
    assert "<u>" not in result


def test_mark_subsup_sub():
    result = markdown_from_adf(_paragraph(
        _text("2", marks=[{"type": "subsup", "attrs": {"type": "sub"}}])
    ))
    assert "~2~" in result


def test_mark_subsup_sup():
    result = markdown_from_adf(_paragraph(
        _text("2", marks=[{"type": "subsup", "attrs": {"type": "sup"}}])
    ))
    assert "^2^" in result


def test_marks_compose_strong_em():
    result = markdown_from_adf(_paragraph(
        _text("x", marks=[{"type": "strong"}, {"type": "em"}])
    ))
    assert "***x***" in result


def test_marks_compose_strong_em_link():
    """strong + em + link on the same text node."""
    result = markdown_from_adf(_paragraph(
        _text("w", marks=[
            {"type": "strong"},
            {"type": "em"},
            {"type": "link", "attrs": {"href": "https://x.com"}},
        ])
    ))
    assert "[***w***](https://x.com)" in result


# ── heading ───────────────────────────────────────────────────────────────────

def test_heading_h1():
    result = markdown_from_adf(_heading(1, _text("Title")))
    assert result.strip().startswith("# Title")


def test_heading_h3():
    result = markdown_from_adf(_heading(3, _text("Section")))
    assert result.strip().startswith("### Section")


# ── lists ─────────────────────────────────────────────────────────────────────

def test_bullet_list():
    result = markdown_from_adf(_bullet_list(
        _list_item(_paragraph(_text("alpha"))),
        _list_item(_paragraph(_text("beta"))),
    ))
    assert "- alpha" in result
    assert "- beta" in result


def test_ordered_list():
    result = markdown_from_adf(_ordered_list(
        _list_item(_paragraph(_text("one"))),
        _list_item(_paragraph(_text("two"))),
    ))
    assert "1. one" in result
    assert "2. two" in result


def test_nested_ordered_inside_bullet():
    """Ordered list nested inside a bullet list item — 2-space indent."""
    result = markdown_from_adf(_bullet_list(
        _list_item(
            _paragraph(_text("outer")),
            _ordered_list(
                _list_item(_paragraph(_text("inner-1"))),
                _list_item(_paragraph(_text("inner-2"))),
            ),
        )
    ))
    assert "- outer" in result
    assert "  1. inner-1" in result
    assert "  2. inner-2" in result


# ── code block ────────────────────────────────────────────────────────────────

def test_code_block_language_and_whitespace():
    """Code block preserves whitespace + language tag."""
    code = "def foo():\n    return 42"
    result = markdown_from_adf(_code_block(_text(code), language="python"))
    assert "```python" in result
    assert code in result
    assert "```" in result


def test_code_block_no_language():
    result = markdown_from_adf({
        "type": "codeBlock",
        "attrs": {},
        "content": [{"type": "text", "text": "plain code"}],
    })
    assert "```\n" in result
    assert "plain code" in result


# ── blockquote ────────────────────────────────────────────────────────────────

def test_blockquote():
    result = markdown_from_adf(_blockquote(
        _paragraph(_text("quoted text"))
    ))
    assert "> " in result
    assert "quoted text" in result


# ── hardBreak ─────────────────────────────────────────────────────────────────

def test_hard_break():
    result = markdown_from_adf(_paragraph(
        _text("line1"),
        {"type": "hardBreak"},
        _text("line2"),
    ))
    assert "  \n" in result
    assert "line1" in result
    assert "line2" in result


# ── rule ──────────────────────────────────────────────────────────────────────

def test_rule():
    result = markdown_from_adf({"type": "rule"})
    assert "---" in result


# ── mention ───────────────────────────────────────────────────────────────────

def test_mention_with_text_attr():
    result = markdown_from_adf(_paragraph(
        {"type": "mention", "attrs": {"id": "u-1", "text": "@Alice"}}
    ))
    assert "@Alice" in result


def test_mention_fallback_to_display_name():
    """Missing attrs.text → fall back to displayName."""
    result = markdown_from_adf(_paragraph(
        {"type": "mention", "attrs": {"id": "u-2", "displayName": "Bob"}}
    ))
    assert "@Bob" in result


def test_mention_fallback_to_id():
    """Missing attrs.text and displayName → fall back to id."""
    result = markdown_from_adf(_paragraph(
        {"type": "mention", "attrs": {"id": "u-xyz-99"}}
    ))
    assert "@u-xyz-99" in result


def test_mention_all_missing_graceful():
    """All mention attrs missing → no crash, empty or graceful output."""
    result = markdown_from_adf(_paragraph(
        {"type": "mention", "attrs": {}}
    ))
    assert isinstance(result, str)


# ── emoji ─────────────────────────────────────────────────────────────────────

def test_emoji_short_name():
    result = markdown_from_adf(_paragraph(
        {"type": "emoji", "attrs": {"shortName": ":smile:", "text": "😄"}}
    ))
    assert ":smile:" in result


def test_emoji_fallback_to_text():
    result = markdown_from_adf(_paragraph(
        {"type": "emoji", "attrs": {"text": "😄"}}
    ))
    assert "😄" in result


# ── table ─────────────────────────────────────────────────────────────────────

def test_table_with_header_row():
    """GFM table: first row = header, separator row, then data rows."""
    result = markdown_from_adf(_table(
        _table_row(
            _table_header(_paragraph(_text("Name"))),
            _table_header(_paragraph(_text("Age"))),
        ),
        _table_row(
            _table_cell(_paragraph(_text("Alice"))),
            _table_cell(_paragraph(_text("30"))),
        ),
        _table_row(
            _table_cell(_paragraph(_text("Bob"))),
            _table_cell(_paragraph(_text("25"))),
        ),
    ))
    assert "| Name |" in result
    assert "| --- |" in result
    assert "| Alice |" in result
    assert "| Bob |" in result


# ── inlineCard / blockCard ───────────────────────────────────────────────────

def test_inline_card_with_url():
    result = markdown_from_adf(_paragraph(
        {"type": "inlineCard", "attrs": {"url": "https://example.com"}}
    ))
    assert "https://example.com" in result
    assert "[" in result


def test_inline_card_no_url_empty():
    result = markdown_from_adf(_paragraph(
        {"type": "inlineCard", "attrs": {}}
    ))
    assert isinstance(result, str)


# ── panel ─────────────────────────────────────────────────────────────────────

def test_panel_info():
    result = markdown_from_adf({
        "type": "panel",
        "attrs": {"panelType": "info"},
        "content": [_paragraph(_text("important"))],
    })
    assert "ℹ️" in result
    assert "important" in result
    assert "> " in result


def test_panel_warning():
    result = markdown_from_adf({
        "type": "panel",
        "attrs": {"panelType": "warning"},
        "content": [_paragraph(_text("careful"))],
    })
    assert "⚠️" in result


def test_panel_unknown_type():
    result = markdown_from_adf({
        "type": "panel",
        "attrs": {"panelType": "custom"},
        "content": [_paragraph(_text("body"))],
    })
    assert "body" in result


# ── media ─────────────────────────────────────────────────────────────────────

def test_media_with_url():
    result = markdown_from_adf({
        "type": "media",
        "attrs": {"url": "https://example.com/img.png", "alt": "diagram"},
    })
    assert "![diagram](https://example.com/img.png)" in result


def test_media_without_url_breadcrumb():
    result = markdown_from_adf({
        "type": "media",
        "attrs": {"id": "abc-123"},
    })
    assert "<!-- media:abc-123 -->" in result


def test_media_single_container():
    result = markdown_from_adf({
        "type": "mediaSingle",
        "content": [
            {"type": "media", "attrs": {"url": "https://example.com/x.png"}}
        ],
    })
    assert "https://example.com/x.png" in result


# ── unknown nodes ─────────────────────────────────────────────────────────────

def test_unknown_node_with_content_recurses():
    result = markdown_from_adf({
        "type": "thisTypeDoesNotExist",
        "content": [_paragraph(_text("reachable"))],
    })
    assert "reachable" in result


def test_unknown_node_without_content_empty():
    result = markdown_from_adf({"type": "phantom", "attrs": {}})
    assert result == ""


# ── regression gate ───────────────────────────────────────────────────────────

def test_plain_paragraph_markdown_and_text_equivalent():
    """markdown_from_adf and text_from_adf return equivalent strings for a
    plain single-text-child paragraph (the common case)."""
    node = _paragraph(_text("hello world"))
    md = markdown_from_adf(node).strip()
    pt = text_from_adf(node).strip()
    assert md == pt


def test_doc_none_children_no_children_empty():
    assert markdown_from_adf({"type": "doc", "content": []}) == ""
