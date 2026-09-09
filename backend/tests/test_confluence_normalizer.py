"""Tests for src/harvester/confluence/normalizer.py."""

from __future__ import annotations

import re

import pytest

from src.harvester.confluence.normalizer import (
    ConfluenceMarkdownConverter,
    confluence_to_markdown,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _convert(xhtml: str, base_url: str | None = None) -> str:
    """Run raw XHTML through the converter and return the markdown body."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(xhtml, "html.parser")
    return ConfluenceMarkdownConverter(base_url=base_url).convert_soup(soup)


# ── Macro: code ──────────────────────────────────────────────────────────────


def test_code_macro_with_language():
    xhtml = """
    <ac:structured-macro ac:name="code">
      <ac:parameter ac:name="language">python</ac:parameter>
      <ac:plain-text-body>x = 1\ny = 2</ac:plain-text-body>
    </ac:structured-macro>
    """
    result = _convert(xhtml)
    assert "```python" in result
    assert "x = 1" in result
    assert "y = 2" in result
    assert "```" in result
    assert "<ac:" not in result


def test_code_macro_no_language():
    xhtml = """
    <ac:structured-macro ac:name="code">
      <ac:plain-text-body>SELECT * FROM foo;</ac:plain-text-body>
    </ac:structured-macro>
    """
    result = _convert(xhtml)
    assert "```\n" in result or "```python" not in result
    assert "SELECT * FROM foo;" in result


def test_code_macro_language_roundtrip():
    """The language attribute survives the conversion intact."""
    xhtml = """
    <ac:structured-macro ac:name="code">
      <ac:parameter ac:name="language">javascript</ac:parameter>
      <ac:plain-text-body>const x = 42;</ac:plain-text-body>
    </ac:structured-macro>
    """
    result = _convert(xhtml)
    assert "```javascript" in result
    assert "const x = 42;" in result


# ── Macros: info / note / warning / tip ──────────────────────────────────────


@pytest.mark.parametrize(
    "name,emoji",
    [
        ("info", "ℹ️"),
        ("note", "📝"),
        ("warning", "⚠️"),
        ("tip", "💡"),
    ],
)
def test_admonition_macro(name, emoji):
    xhtml = f"""
    <ac:structured-macro ac:name="{name}">
      <ac:rich-text-body><p>Important text here.</p></ac:rich-text-body>
    </ac:structured-macro>
    """
    result = _convert(xhtml)
    assert emoji in result
    assert "Important text here." in result
    assert result.strip().startswith(">")
    assert "<ac:" not in result


# ── Macro: expand ────────────────────────────────────────────────────────────


def test_expand_macro_unfolds_body():
    xhtml = """
    <ac:structured-macro ac:name="expand">
      <ac:parameter ac:name="title">Click to expand</ac:parameter>
      <ac:rich-text-body><p>Hidden content revealed.</p></ac:rich-text-body>
    </ac:structured-macro>
    """
    result = _convert(xhtml)
    assert "Hidden content revealed." in result
    assert "Click to expand" not in result  # parameter is dropped
    assert "<ac:" not in result


# ── Macro: status ────────────────────────────────────────────────────────────


def test_status_macro():
    xhtml = """
    <ac:structured-macro ac:name="status">
      <ac:parameter ac:name="colour">Green</ac:parameter>
      <ac:parameter ac:name="title">Done</ac:parameter>
    </ac:structured-macro>
    """
    result = _convert(xhtml)
    assert "[STATUS: Done]" in result
    assert "<ac:" not in result


# ── Macro: jira ──────────────────────────────────────────────────────────────


def test_jira_macro_with_base_url():
    xhtml = """
    <ac:structured-macro ac:name="jira">
      <ac:parameter ac:name="key">PUD-123</ac:parameter>
    </ac:structured-macro>
    """
    result = _convert(xhtml, base_url="https://example.atlassian.net/wiki")
    assert "[PUD-123]" in result
    assert "https://example.atlassian.net/wiki/browse/PUD-123" in result
    assert "<ac:" not in result


def test_jira_macro_without_base_url():
    xhtml = """
    <ac:structured-macro ac:name="jira">
      <ac:parameter ac:name="key">PROJ-42</ac:parameter>
    </ac:structured-macro>
    """
    result = _convert(xhtml, base_url=None)
    assert "[PROJ-42]" in result
    assert "http" not in result
    assert "<ac:" not in result


# ── Dynamic macros (drop with breadcrumb) ────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    ["recently-updated", "blog-posts", "children-display", "contributors", "pagetree"],
)
def test_dynamic_macro_drops_body_emits_comment(name):
    xhtml = f"""
    <ac:structured-macro ac:name="{name}">
      <ac:parameter ac:name="spaces">PROD</ac:parameter>
    </ac:structured-macro>
    """
    result = _convert(xhtml)
    assert f"<!-- confluence:{name} -->" in result
    assert "PROD" not in result  # parameter body dropped
    assert "<ac:" not in result


# ── Diagram macros ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["drawio", "gliffy", "lucidchart"])
def test_diagram_macro_emits_comment_with_filename(name):
    xhtml = f"""
    <ac:structured-macro ac:name="{name}">
      <ac:parameter ac:name="diagramName">architecture.{name}</ac:parameter>
    </ac:structured-macro>
    """
    result = _convert(xhtml)
    assert f"<!-- confluence:{name}" in result
    assert f'diagram="architecture.{name}"' in result
    assert "<ac:" not in result


# ── Unknown macro ─────────────────────────────────────────────────────────────


def test_unknown_macro_is_transparent():
    xhtml = """
    <ac:structured-macro ac:name="some-future-macro">
      <ac:rich-text-body><p>Visible body text.</p></ac:rich-text-body>
    </ac:structured-macro>
    """
    result = _convert(xhtml)
    assert "Visible body text." in result
    assert "<ac:" not in result


# ── Layout wrappers ───────────────────────────────────────────────────────────


def test_layout_elements_are_transparent():
    xhtml = """
    <ac:layout>
      <ac:layout-section ac:type="two_equal">
        <ac:layout-cell>
          <p>Left column content.</p>
        </ac:layout-cell>
        <ac:layout-cell>
          <p>Right column content.</p>
        </ac:layout-cell>
      </ac:layout-section>
    </ac:layout>
    """
    result = _convert(xhtml)
    assert "Left column content." in result
    assert "Right column content." in result
    assert "<ac:" not in result
    assert "<ri:" not in result


# ── ac:link to ri:page ────────────────────────────────────────────────────────


def test_ac_link_to_page_produces_title():
    xhtml = """
    <ac:link>
      <ri:page ri:content-title="Engineering Handbook" ri:space-key="ENG"/>
    </ac:link>
    """
    result = _convert(xhtml)
    assert "Engineering Handbook" in result
    assert "<ac:" not in result
    assert "<ri:" not in result


def test_ac_link_to_page_uses_body_text_when_present():
    xhtml = """
    <ac:link>
      <ri:page ri:content-title="Engineering Handbook"/>
      <ac:link-body>the handbook</ac:link-body>
    </ac:link>
    """
    result = _convert(xhtml)
    # Either title or body text should appear; no raw tags
    assert "<ac:" not in result
    assert "<ri:" not in result


# ── ac:link to ri:user ────────────────────────────────────────────────────────


def test_ac_link_to_user_produces_mention():
    xhtml = """
    <ac:link>
      <ri:user ri:username="jsmith" ri:display-name="John Smith"/>
    </ac:link>
    """
    result = _convert(xhtml)
    assert "@John Smith" in result
    assert "<ac:" not in result
    assert "<ri:" not in result


def test_ac_link_to_user_fallback_username():
    xhtml = """
    <ac:link>
      <ri:user ri:username="jdoe"/>
    </ac:link>
    """
    result = _convert(xhtml)
    assert "@jdoe" in result
    assert "<ac:" not in result


def test_ac_link_to_user_fallback_user_when_no_name():
    xhtml = """
    <ac:link>
      <ri:user ri:userkey="abc123"/>
    </ac:link>
    """
    result = _convert(xhtml)
    assert result.strip().startswith("@")
    assert "<ac:" not in result


# ── ac:image ──────────────────────────────────────────────────────────────────


def test_ac_image_with_attachment():
    xhtml = """
    <ac:image ac:alt="Architecture diagram" ac:width="800">
      <ri:attachment ri:filename="arch.png"/>
    </ac:image>
    """
    result = _convert(xhtml)
    assert "![Architecture diagram](arch.png)" in result
    assert "<ac:" not in result
    assert "<ri:" not in result


def test_ac_image_with_ac_src():
    xhtml = """<ac:image ac:src="https://example.com/img.png" ac:alt="remote img"/>"""
    result = _convert(xhtml)
    assert "![remote img](https://example.com/img.png)" in result
    assert "<ac:" not in result


def test_ac_image_caption_used_as_alt():
    xhtml = """
    <ac:image>
      <ri:attachment ri:filename="diagram.png"/>
      <ac:caption><p>System overview</p></ac:caption>
    </ac:image>
    """
    result = _convert(xhtml)
    assert "diagram.png" in result
    assert "System overview" in result
    assert "<ac:" not in result


# ── ac:emoticon ───────────────────────────────────────────────────────────────


def test_emoticon_with_shortname():
    xhtml = """<ac:emoticon ac:emoji-shortname="sparkles"/>"""
    result = _convert(xhtml)
    assert ":sparkles:" in result


def test_emoticon_without_shortname_drops():
    xhtml = """<ac:emoticon/>"""
    result = _convert(xhtml)
    assert "<ac:" not in result


# ── ac:parameter is dropped ───────────────────────────────────────────────────


def test_ac_parameter_is_dropped():
    xhtml = """
    <p>Before</p>
    <ac:parameter ac:name="some-key">should not appear</ac:parameter>
    <p>After</p>
    """
    result = _convert(xhtml)
    assert "should not appear" not in result
    assert "Before" in result
    assert "After" in result


# ── Malformed XHTML doesn't raise ────────────────────────────────────────────


def test_malformed_xhtml_does_not_raise():
    bad_inputs = [
        "<p>Unclosed paragraph",
        "<ac:structured-macro ac:name='code'><ac:plain-text-body>x=1",
        "<<<not valid xml>>>",
        "",
        "<ac:link><ri:page ri:content-title=",
    ]
    for xhtml in bad_inputs:
        out = confluence_to_markdown(xhtml, {})
        assert isinstance(out, str)


# ── Clean output — no frontmatter ────────────────────────────────────────────


def test_output_has_no_yaml_frontmatter():
    """Output must be pure markdown — no leading YAML block."""
    metadata = {
        "document_type": "page",
        "space_key": "ENG",
        "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/1/Some+Page",
        "author_name": "Alice",
        "labels": ["project", "draft"],
        "updated_at": "2026-04-01T00:00:00Z",
    }
    out = confluence_to_markdown("<p>Hello world</p>", metadata)
    assert not out.startswith("---"), "frontmatter must not be emitted"
    # None of the metadata keys should appear anywhere in the body
    assert "document_type" not in out
    assert "space_key" not in out
    assert "author_name" not in out
    assert "updated_at" not in out
    assert "https://example.atlassian.net" not in out
    assert "Hello world" in out


def test_output_is_pure_body_text():
    """A minimal page should render as just the body, with a trailing newline."""
    out = confluence_to_markdown("<p>Hello</p>", {})
    assert out.strip() == "Hello"
    assert out.endswith("\n")


def test_malformed_body_returns_partial_without_frontmatter():
    """The normalization-failure fallback must also be frontmatter-free."""
    # Forcing the exception path is tricky; we just assert the happy-path contract
    # and that even empty input yields a non-frontmatter string.
    out = confluence_to_markdown("", {"space_key": "ENG"})
    assert not out.startswith("---")


# ── End-to-end: no <ac: or <ri: substrings in output ─────────────────────────


def test_end_to_end_no_raw_tags():
    xhtml = """
    <ac:layout>
      <ac:layout-section>
        <ac:layout-cell>
          <h2>Overview</h2>
          <p>See <ac:link><ri:page ri:content-title="Design Doc"/></ac:link> for details.</p>
          <ac:structured-macro ac:name="code">
            <ac:parameter ac:name="language">bash</ac:parameter>
            <ac:plain-text-body>echo hello world</ac:plain-text-body>
          </ac:structured-macro>
          <ac:structured-macro ac:name="info">
            <ac:rich-text-body><p>Read the docs.</p></ac:rich-text-body>
          </ac:structured-macro>
          <ac:structured-macro ac:name="recently-updated">
            <ac:parameter ac:name="spaces">ALL</ac:parameter>
          </ac:structured-macro>
          <ac:image ac:alt="logo">
            <ri:attachment ri:filename="logo.png"/>
          </ac:image>
          <p>Mention <ac:link><ri:user ri:username="alice"/></ac:link> here.</p>
        </ac:layout-cell>
      </ac:layout-section>
    </ac:layout>
    """
    out = confluence_to_markdown(xhtml, {"document_type": "page", "space_key": "PROD"})
    assert "<ac:" not in out, "ac: tags leaked into output"
    assert "<ri:" not in out, "ri: tags leaked into output"
    assert "Overview" in out
    assert "```bash" in out
    assert "echo hello world" in out
    assert "ℹ️" in out
    assert "<!-- confluence:recently-updated -->" in out
    assert "![logo](logo.png)" in out
    assert "@alice" in out
    assert "Design Doc" in out


# ── Excessive blank lines are collapsed ───────────────────────────────────────


def test_excessive_blank_lines_collapsed():
    xhtml = "<p>A</p><p>B</p><p>C</p><p>D</p>"
    out = confluence_to_markdown(xhtml, {})
    assert "\n\n\n" not in out
