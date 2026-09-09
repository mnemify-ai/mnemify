"""Fixture-backed parser tests for ``confluence.extractor.html_to_plain_text``.

ATL-52 consolidates the ATL-12 parametrised edge cases against the
ATL-50 JSON fixtures so the flattener is exercised on exactly the
``body.storage.value`` payloads a live harvest would see.  The file is
named ``test_confluence_parser.py`` (per the plan row) even though the
module is ``extractor.py`` — this mirrors the Obsidian
``parser.py``/``test_obsidian_parser.py`` convention.

Coverage (consolidated):

1. Code block inside ``<ac:structured-macro name="code">`` — body
   preserved verbatim, ``ac:parameter`` noise absent.
2. Two-row table rows separated by newlines, header included, no tags.
3. Nested ``info`` macro — prose inside ``<ac:rich-text-body>`` survives.
4. Emoji glyph round-trips byte-for-byte.
5. Empty body → empty string.
6. Truncated / malformed XHTML does not crash the parser.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.harvester.confluence.extractor import html_to_plain_text

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "confluence"


def _load_body(name: str) -> str:
    """Extract ``body.storage.value`` from a frozen full-page fixture."""
    page = json.loads((FIXTURE_DIR / name).read_text())
    return page["body"]["storage"]["value"]


# ── Rich XHTML fixture — covers code, table, macro, emoji ─────────


@pytest.fixture(scope="module")
def rich_text() -> str:
    return html_to_plain_text(_load_body("page_xhtml_rich.json"))


def test_parser_preserves_code_block_body(rich_text: str):
    """The ``def migrate`` function body survives the macro flatten intact.

    In particular, the ``db.execute("ALTER TABLE users ADD COLUMN tier INT")``
    line must be byte-identical to the fixture — the XHTML parser must
    unwrap the ``<ac:plain-text-body>`` + CDATA without re-escaping.
    """
    assert "def migrate(db):" in rich_text
    assert 'db.execute("ALTER TABLE users ADD COLUMN tier INT")' in rich_text
    assert "return db.row_count" in rich_text


def test_parser_drops_ac_parameter_macro_config(rich_text: str):
    """``<ac:parameter>language=python</ac:parameter>`` is noise, not prose.

    The ``python`` token inside the parameter tag must not appear in
    the flattened output — it is language metadata for the code macro,
    not user-authored content.
    """
    # "python" should not appear anywhere — the only place it lived in
    # the fixture was inside an ``ac:parameter`` tag.
    assert "python" not in rich_text


def test_parser_flattens_table_rows(rich_text: str):
    """Each <tr> becomes its own line; <td> / <th> content is preserved."""
    # Headers present
    assert "Step" in rich_text
    assert "Owner" in rich_text
    # Body rows present
    assert "Migrate" in rich_text
    assert "Verify" in rich_text
    # Tags dropped
    assert "<tr" not in rich_text
    assert "<td" not in rich_text


def test_parser_unwraps_info_macro_prose(rich_text: str):
    """Prose inside ``<ac:structured-macro name="info"><ac:rich-text-body>``
    is transparent to the flattener — the paragraph survives."""
    assert "Remember to notify on-call before running." in rich_text


def test_parser_round_trips_emoji(rich_text: str):
    """Emoji glyphs pass through untouched (no HTML-entity escaping)."""
    assert "🚀" in rich_text


def test_parser_collapses_excess_blank_lines(rich_text: str):
    """Three or more consecutive newlines collapse to a blank-line pair."""
    assert "\n\n\n" not in rich_text


# ── Empty body ────────────────────────────────────────────────────


def test_parser_empty_body_returns_empty_string():
    """A ``body.storage.value`` of ``""`` yields ``""`` without raising."""
    assert html_to_plain_text("") == ""


# ── Malformed body ────────────────────────────────────────────────


def test_parser_handles_truncated_xhtml_fixture():
    """The ATL-50 malformed-body fixture must not crash the flattener.

    The fixture contains an unclosed ``<p>`` + ``<strong>`` + a
    truncated ``<ac:plain-text-body><![CDATA[print("truncated`` — bs4's
    permissive ``html.parser`` must recover something and return a
    string, not raise.
    """
    body = _load_body("page_malformed_body.json")
    text = html_to_plain_text(body)
    # Does not raise, returns a str
    assert isinstance(text, str)
    # Recoverable prose survives
    assert "This paragraph never closes" in text
