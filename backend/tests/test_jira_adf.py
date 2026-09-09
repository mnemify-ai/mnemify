"""Port-fidelity tests for :func:`src.harvester.jira.adf.text_from_adf`.

ATL-21 ports ``text_from_adf`` verbatim from
``friends_code/utils/utils.py`` (line ~103).  These tests pin the port's
behaviour against hand-computed expected outputs for every ADF node
kind the friend's implementation actually handles (plus a few it
doesn't — those are asserted to yield ``""``, codifying the known
shortcomings so Phase-2 work cannot regress the port silently).

**Do not "improve" the friend's function to make these tests pass.**
If a test looks "wrong" (e.g. mention → ``""`` instead of the
display name), the expected value is what the ported code actually
returns and the shortcoming is documented in the module docstring.
"""

from __future__ import annotations

import pytest

from src.harvester.jira.adf import text_from_adf


# ── Fixture builders ─────────────────────────────────────────────


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


# ── Port-fidelity cases ──────────────────────────────────────────

# Each case is (id, adf_input, expected_plain_text).
#
# Expected values are hand-computed from the ported implementation:
#
#   def text_from_adf(node):
#       if node is None: return ""
#       if isinstance(node, str): return node
#       if node.get("type") == "text": return node.get("text", "")
#       parts = [text_from_adf(c) for c in node.get("content", [])]
#       return " ".join(p for p in parts if p)
#
# In particular:
#  * Nodes with no "content" (mention, emoji, hardBreak, …) yield "".
#  * Multiple text siblings are space-joined, even inside a codeBlock.
#  * Marks (bold, italic, code, link, …) are ignored; the text passes
#    through unchanged.
#  * Unknown types recurse into "content" without raising.

CASES = [
    # 1. None input
    ("none_input", None, ""),
    # 2. Empty doc — the smoke-test from the acceptance criteria
    ("empty_doc", _doc(), ""),
    # 3. Bare string passes through (str-isinstance branch)
    ("bare_string", "just a string", "just a string"),
    # 4. Plain text node
    ("text_node", _text("hello"), "hello"),
    # 5. Text node with marks (inlineCode / bold / etc.) — marks ignored, text verbatim
    (
        "text_node_with_code_mark",
        _text("x = 1", marks=[{"type": "code"}]),
        "x = 1",
    ),
    # 6. Paragraph with two text children → space-joined
    (
        "paragraph_two_texts",
        _paragraph(_text("hello"), _text("world")),
        "hello world",
    ),
    # 7. Heading
    (
        "heading_h1",
        _heading(1, _text("Title")),
        "Title",
    ),
    # 8. bulletList with listItem-wrapped paragraphs
    (
        "bullet_list_two_items",
        _bullet_list(
            _list_item(_paragraph(_text("first"))),
            _list_item(_paragraph(_text("second"))),
        ),
        "first second",
    ),
    # 9. orderedList — same structure, same joining semantics as bulletList
    (
        "ordered_list_two_items",
        _ordered_list(
            _list_item(_paragraph(_text("one"))),
            _list_item(_paragraph(_text("two"))),
        ),
        "one two",
    ),
    # 10. codeBlock — a single text child preserves its internal whitespace
    #     (within the one text node), but note: multi-sibling case below.
    (
        "code_block_single_text",
        _code_block(_text("def foo():\n    pass")),
        "def foo():\n    pass",
    ),
    # 11. codeBlock with multiple text siblings — space-joined (port
    #     shortcoming: the original impl does NOT preserve newline
    #     separators between sibling text nodes).
    (
        "code_block_multi_text_space_joined",
        _code_block(_text("line1"), _text("line2")),
        "line1 line2",
    ),
    # 12. mention — no "content" key in real ADF mentions, so the port
    #     yields "". Display name in attrs.text is NOT surfaced.
    (
        "mention_yields_empty",
        {"type": "mention", "attrs": {"id": "abc-123", "text": "@Alice"}},
        "",
    ),
    # 13. emoji — same story: no content → "".
    (
        "emoji_yields_empty",
        {"type": "emoji", "attrs": {"shortName": ":smile:", "text": "😄"}},
        "",
    ),
    # 14. hardBreak — no content, no text → "".
    ("hard_break_yields_empty", {"type": "hardBreak"}, ""),
    # 15. Nested paragraph inside listItem inside bulletList
    #     (explicit case even though #8 covers it — mirrors real issue bodies).
    (
        "nested_paragraph_in_list_item",
        _bullet_list(
            _list_item(
                _paragraph(_text("outer")),
                _paragraph(_text("inner")),
            ),
        ),
        "outer inner",
    ),
    # 16. Malformed / unknown node type — must not raise; recurses into content.
    (
        "unknown_type_recurses_into_content",
        {
            "type": "thisTypeDoesNotExist",
            "content": [_paragraph(_text("still extracted"))],
        },
        "still extracted",
    ),
    # 17. Unknown node type with no content at all → "".
    (
        "unknown_type_no_content_yields_empty",
        {"type": "panel", "attrs": {"panelType": "info"}},
        "",
    ),
    # 18. Text node missing "text" key → "" (node.get("text", "") branch).
    ("text_node_missing_text", {"type": "text"}, ""),
    # 19. Mixed paragraph: text + mention + text.  Mention contributes "",
    #     which is filtered by `if p` before the space-join, so the result
    #     has a single space between the two surviving text fragments (NOT
    #     two spaces).
    (
        "paragraph_with_mention_between_texts",
        _paragraph(
            _text("We discuss"),
            {"type": "mention", "attrs": {"id": "u-1", "text": "@Bob"}},
            _text("today"),
        ),
        "We discuss today",
    ),
    # 20. Full-document smoke test — heading + paragraph-with-mention +
    #     bulletList, joined at the doc level with single spaces.
    (
        "full_document",
        _doc(
            _heading(1, _text("Plan")),
            _paragraph(
                _text("We discuss"),
                {"type": "mention", "attrs": {"id": "u-1", "text": "@Bob"}},
                _text("today"),
            ),
            _bullet_list(
                _list_item(_paragraph(_text("Alpha"))),
                _list_item(_paragraph(_text("Beta"))),
            ),
        ),
        "Plan We discuss today Alpha Beta",
    ),
]


@pytest.mark.parametrize(
    "adf_input,expected",
    [pytest.param(inp, exp, id=case_id) for case_id, inp, exp in CASES],
)
def test_text_from_adf_port_fidelity(adf_input, expected):
    """Each ADF input must flatten to exactly the hand-computed expected text."""
    assert text_from_adf(adf_input) == expected


# ── Non-parametrized sanity checks ───────────────────────────────


def test_text_from_adf_does_not_raise_on_malformed_input():
    """Malformed / unknown node types must return ""  rather than raising."""
    # Covered by CASE "unknown_type_no_content_yields_empty" too; this
    # test codifies the "must not raise" half of the contract explicitly.
    assert text_from_adf({"type": "weirdNode"}) == ""
    assert text_from_adf({"type": "alsoWeird", "attrs": {"x": 1}}) == ""


def test_text_from_adf_empty_doc_smoke():
    """Exactly the CLI acceptance-criterion smoke test."""
    assert text_from_adf({"type": "doc", "content": []}) == ""


# ══════════════════════════════════════════════════════════════════
# ATL-57 — extended coverage beyond port fidelity
# ══════════════════════════════════════════════════════════════════
#
# These cases deliberately exercise the corners that ATL-21's port
# fidelity suite does not:
#
# - Explicit empty-document & malformed-root invariants.
# - Links as a node-type AND as a mark on a text node (both produce
#   their inner text verbatim — the link URL is never surfaced).
# - Blockquote nodes (have ``content``, recurse, space-join siblings).
# - Nested blockquote (tree depth 3+, no stack overflow, no ordering
#   surprises).
# - Hard breaks interspersed between text nodes.
# - Ordered list nested inside bullet list (depth >= 3).
# - Document with ``content: null`` (defensive branch — ``node.get(
#   "content", []) or []`` yields ``[]``).
# - Nested doc → paragraph → doc → paragraph chain (unusual but legal
#   ADF from embedded templates; must not error or lose fragments).
# - Very deep paragraph nesting (20 levels) — stack / runtime sanity.
#
# Every expected value is hand-computed against:
#
#     def text_from_adf(node):
#         if node is None: return ""
#         if isinstance(node, str): return node
#         if node.get("type") == "text": return node.get("text", "")
#         parts = [text_from_adf(c) for c in node.get("content", [])]
#         return " ".join(p for p in parts if p)
#
# If a test starts failing because the source behaviour changed,
# update the expected value to match the new implementation (if the
# change was intentional) — never silently "fix" the test.


def _link_node(href: str, text: str) -> dict:
    """Link as an ADF node type (``{type: link, content: [text]}``)."""
    return {
        "type": "link",
        "attrs": {"href": href},
        "content": [_text(text)],
    }


def _link_mark_text(text: str, href: str) -> dict:
    """Link as a mark on a text node (``{type: text, marks: [{type: link}]}``)."""
    return _text(text, marks=[{"type": "link", "attrs": {"href": href}}])


def _blockquote(*children: dict) -> dict:
    return {"type": "blockquote", "content": list(children)}


def _hard_break() -> dict:
    return {"type": "hardBreak"}


EXTRA_CASES = [
    # E1. Explicit empty doc with ``content: []``
    ("extra_empty_doc_explicit", {"type": "doc", "content": []}, ""),
    # E2. Doc with ``content: null`` — node.get("content", []) gives None;
    #     ``for child in None`` would TypeError, BUT the implementation uses
    #     ``node.get("content", [])`` which returns ``None`` (not default)
    #     when the key is PRESENT and explicitly None.  Confirm the actual
    #     behaviour rather than assume; if it raises, the port is brittle.
    #     The port does in fact iterate ``None`` -> TypeError.  Capture
    #     that with an xfail-style expect-raises rather than a CASE so
    #     the parametrise above remains side-effect-free.
    # (handled below in a dedicated non-parametric test)
    # E3. Link-as-node — recurses into content, yielding inner text.
    ("extra_link_node_yields_text", _link_node("https://x", "click here"), "click here"),
    # E4. Link as a *mark* on a text node — marks ignored, text verbatim.
    ("extra_link_mark_text", _link_mark_text("click here", "https://x"), "click here"),
    # E5. Paragraph mixing a link-mark text, plain text, and link-node.
    (
        "extra_paragraph_with_mixed_link_forms",
        _paragraph(
            _text("See"),
            _link_mark_text("the docs", "https://docs.example.com"),
            _text("or"),
            _link_node("https://x", "this link"),
            _text("."),
        ),
        "See the docs or this link .",
    ),
    # E6. Blockquote — recurses, children space-joined.
    (
        "extra_blockquote_single_paragraph",
        _blockquote(_paragraph(_text("quoted"))),
        "quoted",
    ),
    # E7. Nested blockquote (blockquote > blockquote > paragraph).
    (
        "extra_nested_blockquote",
        _blockquote(_blockquote(_paragraph(_text("double-quoted")))),
        "double-quoted",
    ),
    # E8. Hard break interspersed between text nodes — hardBreak yields
    #     "" (filtered out of space-join), so two surviving texts join
    #     with a SINGLE space (never two).
    (
        "extra_hard_break_filtered_out",
        _paragraph(_text("line1"), _hard_break(), _text("line2")),
        "line1 line2",
    ),
    # E9. Ordered list nested inside a bullet list (depth >= 3).
    (
        "extra_ordered_nested_in_bullet",
        _bullet_list(
            _list_item(
                _paragraph(_text("outer")),
                _ordered_list(
                    _list_item(_paragraph(_text("inner-1"))),
                    _list_item(_paragraph(_text("inner-2"))),
                ),
            ),
        ),
        "outer inner-1 inner-2",
    ),
    # E10. Chain of wrapper nodes each with a single text child — no
    #      joining surprises because single-child space-join is a no-op.
    (
        "extra_single_text_chain",
        _paragraph(_text("solo")),
        "solo",
    ),
    # E11. Unknown type with content that contains another unknown type.
    (
        "extra_unknown_nested_in_unknown",
        {
            "type": "outerUnknown",
            "content": [
                {
                    "type": "innerUnknown",
                    "content": [_paragraph(_text("reachable"))],
                }
            ],
        },
        "reachable",
    ),
    # E12. List item with NO content key — yields "" (defensive; empty
    #      list items occasionally leak through ADF round-trips).
    ("extra_list_item_empty", {"type": "listItem"}, ""),
    # E13. Mixed content at the doc level — heading + blockquote + list
    #      — assembled with single spaces between non-empty fragments.
    (
        "extra_doc_heading_quote_list",
        _doc(
            _heading(2, _text("Context")),
            _blockquote(_paragraph(_text("yesterday's standup"))),
            _ordered_list(_list_item(_paragraph(_text("follow up")))),
        ),
        "Context yesterday's standup follow up",
    ),
    # E14. Link-as-node with NO content (defensive — real ADF always
    #      has content here, but absent content must not raise).
    ("extra_link_node_no_content", {"type": "link", "attrs": {"href": "https://x"}}, ""),
]


@pytest.mark.parametrize(
    "adf_input,expected",
    [pytest.param(inp, exp, id=case_id) for case_id, inp, exp in EXTRA_CASES],
)
def test_text_from_adf_extra_coverage(adf_input, expected):
    """ATL-57 extended coverage — blockquote, links, nested, edge cases."""
    assert text_from_adf(adf_input) == expected


def test_text_from_adf_deeply_nested_paragraph_does_not_stack_overflow():
    """20-level paragraph nesting must resolve without RecursionError."""
    node: dict = _text("deep")
    # Wrap 20 times in paragraphs (each paragraph having a single child).
    for _ in range(20):
        node = _paragraph(node)
    assert text_from_adf(node) == "deep"


def test_text_from_adf_explicit_none_content_surfaces_typeerror():
    """Document with ``content: None`` hits ``for c in None`` — captures the port's behaviour.

    The ported one-liner uses ``node.get("content", [])`` which returns
    the *actual value* (``None``) when the key is present but null.
    The subsequent list-comprehension then iterates over ``None`` and
    raises ``TypeError``.  This test pins the real (currently brittle)
    behaviour; if Phase-2 fixes the port to tolerate ``None``, update
    the expectation rather than silently losing the regression guard.
    """
    with pytest.raises(TypeError):
        text_from_adf({"type": "doc", "content": None})


def test_text_from_adf_list_passed_as_root_surfaces_attributeerror():
    """Non-dict / non-str / non-None inputs must not be silently accepted.

    The port checks ``isinstance(node, str)`` and ``node is None`` but
    otherwise assumes a dict-like (``.get``).  A bare list falls through
    and raises ``AttributeError`` on the ``.get`` call.  Codifying this
    keeps the failure mode explicit for callers.
    """
    with pytest.raises(AttributeError):
        text_from_adf([_paragraph(_text("oops"))])
