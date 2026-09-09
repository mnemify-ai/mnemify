"""Confluence XHTML storage-format → clean markdown normalizer.

Public API: ``confluence_to_markdown(xhtml, metadata, *, base_url=None) -> str``.

The output is pure markdown body — no YAML frontmatter, no metadata headers.
All structured metadata (url, space_key, labels, etc.) lives in the harvest
manifest's ``documents.metadata`` JSON column instead. The ``metadata``
parameter is retained for future use (e.g. resolving page-title links) but
is not written into the output.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import markdownify
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_EMOJI_FOR_ADMONITION = {
    "info": "ℹ️",
    "note": "📝",
    "warning": "⚠️",
    "tip": "💡",
}

_DYNAMIC_MACROS = frozenset(
    {"recently-updated", "blog-posts", "children-display", "contributors", "pagetree"}
)

_DIAGRAM_MACROS = frozenset({"drawio", "gliffy", "lucidchart"})

_EXCESSIVE_BLANKS = re.compile(r"\n{3,}")


class ConfluenceMarkdownConverter(markdownify.MarkdownConverter):
    """markdownify subclass with handlers for Confluence XHTML namespaces.

    Pass ``base_url`` to enable Jira macro inline links and Confluence page
    links (e.g. ``https://your-org.atlassian.net/wiki``).
    """

    def __init__(self, *args: Any, base_url: str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._base_url = base_url

    # ── ac:structured-macro ──────────────────────────────────────────

    def convert_ac_structured_macro(self, el, text, **kwargs):
        name = el.get("ac:name", "")

        if name == "code":
            return self._macro_code(el)

        if name in _EMOJI_FOR_ADMONITION:
            return self._macro_admonition(name, text)

        if name == "expand":
            stripped = text.strip()
            return f"\n\n{stripped}\n\n" if stripped else ""

        if name == "status":
            return self._macro_status(el)

        if name == "jira":
            return self._macro_jira(el)

        if name in _DYNAMIC_MACROS:
            return f"\n\n<!-- confluence:{name} -->\n\n"

        if name in _DIAGRAM_MACROS:
            return self._macro_diagram(name, el)

        # Unknown macro — transparent (drop wrapper, keep converted children)
        return text

    def _macro_code(self, el) -> str:
        lang = ""
        body = ""
        for child in el.children:
            cname = getattr(child, "name", None)
            if cname == "ac:parameter" and child.get("ac:name") == "language":
                lang = child.get_text().strip()
            elif cname in ("ac:plain-text-body", "ac:rich-text-body"):
                body = child.get_text()
        return f"\n\n```{lang}\n{body}\n```\n\n"

    def _macro_admonition(self, name: str, text: str) -> str:
        emoji = _EMOJI_FOR_ADMONITION[name]
        body = text.strip()
        if not body:
            return f"\n\n> {emoji}\n\n"
        lines = body.splitlines()
        quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in lines)
        return f"\n\n> {emoji}\n{quoted}\n\n"

    def _macro_status(self, el) -> str:
        label = ""
        for child in el.children:
            cname = getattr(child, "name", None)
            if cname == "ac:parameter" and child.get("ac:name") == "title":
                label = child.get_text().strip()
                break
        return f"[STATUS: {label}]"

    def _macro_jira(self, el) -> str:
        key = ""
        for child in el.children:
            cname = getattr(child, "name", None)
            if cname == "ac:parameter" and child.get("ac:name") == "key":
                key = child.get_text().strip()
                break
        if not key:
            return ""
        if self._base_url:
            return f"[{key}]({self._base_url.rstrip('/')}/browse/{key})"
        return f"[{key}]"

    def _macro_diagram(self, name: str, el) -> str:
        filename = ""
        for child in el.children:
            cname = getattr(child, "name", None)
            if cname == "ac:parameter":
                param_name = child.get("ac:name", "")
                if param_name in ("diagramName", "name", "filename"):
                    filename = child.get_text().strip()
                    break
        return f'\n\n<!-- confluence:{name} diagram="{filename}" -->\n\n'

    # ── ac:link ──────────────────────────────────────────────────────

    def convert_ac_link(self, el, text, **kwargs):
        user = el.find("ri:user")
        if user:
            display = (
                user.get("ri:display-name")
                or user.get("ri:username")
                or user.get("ri:userkey")
                or "user"
            )
            return f"@{display}"

        page = el.find("ri:page")
        if page:
            title = page.get("ri:content-title") or text.strip() or "page"
            return title

        # Generic link with body text
        return text or ""

    # ── ac:image ─────────────────────────────────────────────────────

    def convert_ac_image(self, el, text, **kwargs):
        # Most Confluence images reference an attachment rather than a URL
        att = el.find("ri:attachment")
        if att:
            src = att.get("ri:filename") or ""
        else:
            src = el.get("ac:src") or ""

        alt = el.get("ac:alt") or ""
        if not alt:
            caption = el.find("ac:caption")
            if caption:
                alt = caption.get_text().strip()

        if not src:
            return text or ""
        return f"![{alt}]({src})"

    # ── Layout wrappers (transparent) ────────────────────────────────

    def convert_ac_layout(self, el, text, **kwargs):
        return text

    def convert_ac_layout_section(self, el, text, **kwargs):
        return text

    def convert_ac_layout_cell(self, el, text, **kwargs):
        return text

    # ── ac:parameter — drop entirely ─────────────────────────────────

    def convert_ac_parameter(self, el, text, **kwargs):
        return ""

    # ── ac:emoticon ──────────────────────────────────────────────────

    def convert_ac_emoticon(self, el, text, **kwargs):
        shortname = el.get("ac:emoji-shortname") or el.get("ac:name", "")
        return f":{shortname}:" if shortname else ""

    # ri:* tags have no convert_ methods → markdownify returns converted
    # children (transparent), which is the correct fallback for ri:space,
    # ri:attachment (already consumed by convert_ac_image), etc.


# ── Module-level helpers ──────────────────────────────────────────────


def confluence_to_markdown(
    xhtml: str,
    metadata: dict,
    *,
    base_url: str | None = None,
) -> str:
    """Convert Confluence XHTML storage format to clean markdown.

    Args:
        xhtml: Raw XHTML from ``body.storage.value``.
        metadata: Reserved for future use (e.g. page-title link resolution).
            Not written into the output — metadata lives in the manifest.
        base_url: Confluence site base URL for Jira macro links.

    Returns:
        Clean markdown body, no frontmatter, trailing newline.
    """
    try:
        soup = BeautifulSoup(xhtml, "html.parser")
        converter = ConfluenceMarkdownConverter(base_url=base_url)
        body = converter.convert_soup(soup)
        body = _EXCESSIVE_BLANKS.sub("\n\n", body)
    except Exception:
        logger.exception("Confluence XHTML normalization failed for content starting: %.80r", xhtml)
        partial = xhtml[:500] if xhtml else ""
        return f"<!-- normalization failed -->\n\n{partial}\n"

    return f"{body.strip()}\n"
