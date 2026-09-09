"""ADF → plain-text extractor for Jira issue bodies.

Jira Cloud's issue ``description``, ``comment[].body``, and some custom
fields are serialised as Atlassian Document Format (ADF) — a recursive
JSON tree of node objects with ``type``, ``content``, ``text``, and
``marks`` keys.

The plugin stores the raw issue JSON byte-for-byte in :class:`RawDocument`
(format ``"json"``) and only flattens ADF to plain text when the
harvest manifest needs a lossy snippet for filter decisions and the
Phase-2 compiler needs a baseline indexable body.

Contract (as implemented by the ported :func:`text_from_adf`):

- ``None`` inputs yield ``""``.
- Raw ``str`` inputs pass through untouched.
- Nodes with ``type == "text"`` contribute their ``text`` attribute
  verbatim (missing ``text`` → ``""``).
- All other nodes recurse into their ``content`` list; the resulting
  non-empty fragments are joined by a single space.
- Nodes with no ``content`` key (``mention``, ``emoji``, ``hardBreak``,
  malformed / unknown types, ...) yield ``""`` — the function does **not**
  dereference node-specific attrs like ``attrs.text`` /
  ``attrs.displayName`` / ``attrs.shortName``, and does **not** preserve
  ``codeBlock`` whitespace (children are space-joined like any other
  container).  These shortcomings are inherited from the source
  implementation; fixing them is out of scope for this Phase-1 verbatim
  port and belongs in Phase-2 compiler work.

The analogous helper on the Confluence side is ``html_to_plain_text``
in ``src/harvester/confluence/extractor.py``.
"""

from __future__ import annotations

import re

from src.harvester import report_extraction_warning


# Ported from friends_code/utils/utils.py (Atlassian Document Format → plain text).
def text_from_adf(node) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if node.get("type") == "text":
        return node.get("text", "")
    parts = [text_from_adf(child) for child in node.get("content", [])]
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# ADF → GitHub-Flavored Markdown
# ---------------------------------------------------------------------------

_PANEL_EMOJI: dict[str, str] = {
    "info": "ℹ️",
    "note": "📝",
    "warning": "⚠️",
    "error": "❗",
    "success": "✅",
}


def markdown_from_adf(node: dict | None) -> str:
    """Convert an ADF node tree to GitHub-Flavored Markdown.

    Unlike :func:`text_from_adf` this function preserves rich structure:
    headings, bullet/ordered lists, code blocks, tables, inline marks
    (bold, italic, code, links, strikethrough), mentions, emoji, panels,
    and media nodes.

    ``text_from_adf`` is left completely unchanged — it is still used by
    ``extract_plain_text`` for filter-gating.
    """
    if node is None:
        return ""
    result = _render_block(node, list_depth=0)
    # Collapse runs of 3+ newlines to 2.
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


# ── Inline rendering ─────────────────────────────────────────────────────────


def _render_inline(node: dict) -> str:
    t = node.get("type", "")
    if t == "text":
        raw = node.get("text", "")
        marks = node.get("marks") or []
        return _apply_marks(raw, marks)
    if t == "hardBreak":
        return "  \n"
    if t == "mention":
        return _render_mention(node)
    if t == "emoji":
        return _render_emoji(node)
    if t in ("inlineCard", "blockCard"):
        return _render_card(node)
    # Unknown inline — recurse children without adding spaces.
    return "".join(_render_inline(c) for c in (node.get("content") or []))


def _inline_content(node: dict) -> str:
    """Concatenate all inline children of *node* into a single string."""
    return "".join(_render_inline(c) for c in (node.get("content") or []))


def _apply_marks(text: str, marks: list) -> str:
    if not marks or not text:
        return text

    is_code = False
    is_strong = False
    is_em = False
    is_strike = False
    link_href: str | None = None
    sub_sup: str | None = None  # "sub" or "sup"

    for mark in marks:
        mt = mark.get("type", "")
        if mt == "code":
            is_code = True
        elif mt == "strong":
            is_strong = True
        elif mt == "em":
            is_em = True
        elif mt == "strike":
            is_strike = True
        elif mt == "underline":
            pass  # no native underline in markdown — leave plain
        elif mt == "link":
            link_href = (mark.get("attrs") or {}).get("href")
        elif mt == "subsup":
            sub_sup = (mark.get("attrs") or {}).get("type")

    result = text

    if is_code:
        result = f"`{result}`"
    else:
        if sub_sup == "sub":
            result = f"~{result}~"
        elif sub_sup == "sup":
            result = f"^{result}^"

        if is_strong and is_em:
            result = f"***{result}***"
        elif is_strong:
            result = f"**{result}**"
        elif is_em:
            result = f"*{result}*"

        if is_strike:
            result = f"~~{result}~~"

    if link_href:
        result = f"[{result}]({link_href})"

    return result


def _render_mention(node: dict) -> str:
    attrs = node.get("attrs") or {}
    name = attrs.get("text") or attrs.get("displayName") or attrs.get("id") or ""
    if not name:
        return ""
    return name if name.startswith("@") else f"@{name}"


def _render_emoji(node: dict) -> str:
    attrs = node.get("attrs") or {}
    return attrs.get("shortName") or attrs.get("text") or ""


def _render_card(node: dict) -> str:
    attrs = node.get("attrs") or {}
    url = attrs.get("url")
    if not url:
        return ""
    title = attrs.get("title") or url
    return f"[{title}]({url})"


def _render_media(node: dict) -> str:
    attrs = node.get("attrs") or {}
    url = attrs.get("url")
    if url:
        alt = attrs.get("alt") or attrs.get("filename") or ""
        return f"![{alt}]({url})"
    media_id = attrs.get("id") or ""
    return f"<!-- media:{media_id} -->" if media_id else ""


# ── Block rendering ──────────────────────────────────────────────────────────


def _render_block(node: dict, list_depth: int) -> str:
    """Render a block node. Returns a string that may include trailing newlines."""
    t = node.get("type", "")

    if t == "doc":
        parts = [
            _render_block(c, list_depth)
            for c in (node.get("content") or [])
        ]
        return "\n".join(p for p in parts if p)

    if t == "paragraph":
        inline = _inline_content(node)
        return inline + "\n\n" if inline else ""

    if t == "heading":
        level = (node.get("attrs") or {}).get("level", 1)
        hashes = "#" * max(1, min(level, 6))
        return f"{hashes} {_inline_content(node)}\n\n"

    if t == "bulletList":
        return _render_list(node, ordered=False, depth=list_depth)

    if t == "orderedList":
        return _render_list(node, ordered=True, depth=list_depth)

    if t == "codeBlock":
        lang = (node.get("attrs") or {}).get("language") or ""
        code = "".join(
            c.get("text", "")
            for c in (node.get("content") or [])
            if c.get("type") == "text"
        )
        return f"```{lang}\n{code}\n```\n\n"

    if t == "blockquote":
        inner = "\n".join(
            _render_block(c, list_depth)
            for c in (node.get("content") or [])
        )
        inner = inner.rstrip("\n")
        if not inner:
            return ""
        quoted = "\n".join(f"> {line}" for line in inner.split("\n"))
        return quoted + "\n\n"

    if t == "hardBreak":
        return "  \n"

    if t == "rule":
        return "---\n\n"

    if t == "mention":
        return _render_mention(node)

    if t == "emoji":
        return _render_emoji(node)

    if t == "panel":
        return _render_panel(node, list_depth)

    if t == "table":
        return _render_table(node)

    if t in ("inlineCard", "blockCard"):
        rendered = _render_card(node)
        return rendered + "\n\n" if rendered else ""

    if t in ("mediaSingle", "mediaGroup"):
        parts = [
            _render_media(c)
            for c in (node.get("content") or [])
            if c.get("type") == "media"
        ]
        rendered = "".join(parts)
        return rendered + "\n\n" if rendered else ""

    if t == "media":
        rendered = _render_media(node)
        return rendered + "\n\n" if rendered else ""

    # Unknown node — recurse children (best-effort passthrough).
    children = node.get("content")
    if children:
        parts = [_render_block(c, list_depth) for c in children]
        return "\n".join(p for p in parts if p)
    # Unknown leaf block with no children: nothing renders, content is lost.
    report_extraction_warning("jira_unknown_node", t or "unknown")
    return ""


def _render_list(node: dict, ordered: bool, depth: int) -> str:
    indent = "  " * depth
    lines: list[str] = []
    item_number = 1

    for item in node.get("content") or []:
        if item.get("type") != "listItem":
            continue

        prefix = f"{indent}{item_number}. " if ordered else f"{indent}- "
        if ordered:
            item_number += 1

        item_children = item.get("content") or []
        item_lines: list[str] = []
        first_child = True

        for child in item_children:
            ct = child.get("type", "")
            if ct == "paragraph":
                inline = _inline_content(child)
                if first_child:
                    item_lines.append(prefix + inline)
                    first_child = False
                else:
                    # Extra paragraph in same list item.
                    item_lines.append(indent + "  " + inline)
            elif ct in ("bulletList", "orderedList"):
                nested = _render_list(child, ct == "orderedList", depth + 1)
                item_lines.extend(nested.rstrip("\n").split("\n"))
                first_child = False
            else:
                rendered = _render_block(child, depth + 1).rstrip("\n")
                if rendered:
                    for sub_line in rendered.split("\n"):
                        if first_child:
                            item_lines.append(prefix + sub_line)
                            first_child = False
                        else:
                            item_lines.append(indent + "  " + sub_line)

        if first_child:
            item_lines.append(prefix.rstrip())

        lines.extend(item_lines)

    return "\n".join(lines) + "\n\n" if lines else ""


def _render_panel(node: dict, list_depth: int) -> str:
    panel_type = (node.get("attrs") or {}).get("panelType", "")
    emoji = _PANEL_EMOJI.get(panel_type, "📝")

    inner = "\n".join(
        _render_block(c, list_depth)
        for c in (node.get("content") or [])
    ).rstrip("\n")

    if not inner:
        return ""

    lines = inner.split("\n")
    lines[0] = f"{emoji} {lines[0]}"
    quoted = "\n".join(f"> {line}" for line in lines)
    return quoted + "\n\n"


def _render_table(node: dict) -> str:
    rows_data: list[list[str]] = []

    for row in node.get("content") or []:
        if row.get("type") != "tableRow":
            continue
        cells: list[str] = []
        for cell in row.get("content") or []:
            if cell.get("type") not in ("tableCell", "tableHeader"):
                continue
            # Flatten cell content to inline text.
            cell_text = "".join(
                _inline_content(child)
                for child in (cell.get("content") or [])
                if child.get("type") == "paragraph"
            )
            # Escape pipe characters inside cell content.
            cells.append(cell_text.replace("|", "\\|").strip())
        rows_data.append(cells)

    if not rows_data:
        return ""

    col_count = len(rows_data[0])
    header = "| " + " | ".join(rows_data[0]) + " |"
    separator = "| " + " | ".join("---" for _ in range(col_count)) + " |"
    data_rows = []
    for row in rows_data[1:]:
        padded = row + [""] * max(0, col_count - len(row))
        data_rows.append("| " + " | ".join(padded[:col_count]) + " |")

    return "\n".join([header, separator] + data_rows) + "\n\n"
