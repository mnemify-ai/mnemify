"""Unit tests for ``src.harvester.confluence.extractor.html_to_plain_text`` (ATL-12).

Fixture snippets are kept inline as parametrised pairs -- the plan
explicitly avoids a ``tests/fixtures/confluence/`` directory for this
task (ATL-50 builds that later for the orchestrator-level suite).

Coverage map (cf. ATL-12 acceptance criteria):

1.  Plain paragraph.
2.  ``<code>`` block preserves quotes/whitespace verbatim.
3.  ``<pre>`` block preserves leading whitespace.
4.  Two-row table -> rows separated by newline.
5.  Confluence ``code`` macro with ``<ac:parameter>`` noise + CDATA body.
6.  Nested ``info`` macro -- prose inside ``<ac:rich-text-body>`` survives.
7.  ``<br>`` converts to newline.
8.  Runs of 5 blank lines collapse to 2.
9.  Empty input -> empty output.
10. Malformed / unclosed tag handled without raising.
11. HTML entities decoded.
12. Nested list produces newline-separated items.
13. Emoji passes through untouched.
14. Extra: ``<script>`` / ``<style>`` stripped entirely.
15. Extra: ``<ac:parameter>`` value (``python``) absent from macro output.
"""

from __future__ import annotations

import pytest

from src.harvester.confluence.extractor import html_to_plain_text


# ─── Parametrised equality cases ────────────────────────────────────────

# Each tuple: (test_id, input_xhtml, expected_plain_text)
_CASES = [
    (
        "plain_paragraph",
        "<p>Hello world</p>",
        "Hello world",
    ),
    (
        "code_tag_verbatim",
        '<code>print("hi")</code>',
        'print("hi")',
    ),
    (
        "pre_preserves_leading_whitespace",
        "<pre>  indented\n    more</pre>",
        "  indented\n    more",
    ),
    (
        "table_two_rows_newline_separated",
        "<table>"
        "<tr><td>a</td><td>b</td></tr>"
        "<tr><td>c</td><td>d</td></tr>"
        "</table>",
        "ab\ncd",
    ),
    (
        "confluence_code_macro_with_cdata",
        '<ac:structured-macro ac:name="code">'
        '<ac:parameter ac:name="language">python</ac:parameter>'
        "<ac:plain-text-body><![CDATA[x = 1]]></ac:plain-text-body>"
        "</ac:structured-macro>",
        "x = 1",
    ),
    (
        "nested_info_macro_prose_survives",
        '<ac:structured-macro ac:name="info">'
        "<ac:rich-text-body><p>Heads up!</p></ac:rich-text-body>"
        "</ac:structured-macro>",
        "Heads up!",
    ),
    (
        "br_becomes_newline",
        "line1<br/>line2",
        "line1\nline2",
    ),
    (
        "five_blank_lines_collapse_to_two",
        "<p>a</p>\n\n\n\n\n\n<p>b</p>",
        "a\n\nb",
    ),
    (
        "empty_string",
        "",
        "",
    ),
    (
        "malformed_unclosed_tag",
        "<p>unclosed paragraph",
        "unclosed paragraph",
    ),
    (
        "html_entities_decoded",
        "A &amp; B &lt;x&gt; &quot;q&quot;",
        'A & B <x> "q"',
    ),
    (
        "unordered_list_items_newlines",
        "<ul><li>a</li><li>b</li></ul>",
        "a\nb",
    ),
    (
        "emoji_passthrough",
        "<p>Hello \U0001f389</p>",
        "Hello \U0001f389",
    ),
    (
        "script_and_style_stripped",
        "<p>before</p><script>alert(1)</script>"
        "<style>p { color: red; }</style><p>after</p>",
        "before\nafter",
    ),
    (
        "ac_parameter_value_absent",
        # Same as confluence_code_macro_with_cdata but here we only
        # assert that the parameter value (``python``) is gone.  The
        # positive-content assertion lives in its own case above.
        '<ac:structured-macro ac:name="code">'
        '<ac:parameter ac:name="language">python</ac:parameter>'
        "<ac:plain-text-body><![CDATA[x = 1]]></ac:plain-text-body>"
        "</ac:structured-macro>",
        "x = 1",  # the full expected output; negative check runs below
    ),
    (
        "none_equivalent_falsy_returns_empty",
        None,  # explicitly testing the ``if not xhtml`` branch
        "",
    ),
]


@pytest.mark.parametrize(
    ("xhtml", "expected"),
    [pytest.param(raw, exp, id=tid) for tid, raw, exp in _CASES],
)
def test_html_to_plain_text(xhtml, expected):
    assert html_to_plain_text(xhtml) == expected


# ─── Negative-check: ac:parameter value must not leak ──────────────────


def test_ac_parameter_value_does_not_leak_into_output():
    """The config value ``python`` must be dropped, not just ``x = 1`` kept."""
    xhtml = (
        '<ac:structured-macro ac:name="code">'
        '<ac:parameter ac:name="language">python</ac:parameter>'
        "<ac:plain-text-body><![CDATA[x = 1]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )
    out = html_to_plain_text(xhtml)
    assert "python" not in out
    assert "x = 1" in out


# ─── Malformed input must never raise ──────────────────────────────────


@pytest.mark.parametrize(
    "xhtml",
    [
        "<p>",
        "<<>>",
        "<ac:structured-macro ac:name='code'><ac:plain-text-body>",
        "<p><div><span>dangling",
    ],
    ids=[
        "bare_open_p",
        "angle_brackets_only",
        "unclosed_macro_and_body",
        "deeply_nested_unclosed",
    ],
)
def test_malformed_input_does_not_raise(xhtml):
    # Best-effort: must return a string (possibly empty) without raising.
    out = html_to_plain_text(xhtml)
    assert isinstance(out, str)


# ─── Pre contents: block newline injection must be skipped inside ──────


def test_pre_internal_block_tags_do_not_inject_newlines():
    """A ``<p>`` inside a ``<pre>`` (unusual but possible) should not
    add a newline -- the verbatim contract wins."""
    # Two paragraphs fused inside a <pre> -- our block-newline pass must
    # skip them because they are descendants of <pre>.  The output
    # should therefore NOT contain ``ab\n`` from block injection; only
    # whatever literal whitespace lived between them.
    xhtml = "<pre><p>a</p><p>b</p></pre>"
    out = html_to_plain_text(xhtml)
    # No block-injected newline between ``a`` and ``b``.
    assert out == "ab"


# ─── Pre inside a document keeps indentation mid-stream ────────────────


def test_pre_leading_whitespace_survives_when_embedded():
    xhtml = "<p>intro</p><pre>  code line</pre><p>outro</p>"
    out = html_to_plain_text(xhtml)
    # Intro and outro bracket the <pre>, its leading spaces survive in-between.
    assert "  code line" in out
    assert out.startswith("intro")
    assert out.endswith("outro")
