"""XHTML -> plain-text extractor for Confluence ``body.storage`` payloads.

The Confluence ``storage`` format is XHTML with ``<ac:...>`` / ``<ri:...>``
extensions for macros, inline tasks, embedded attachments, etc.  The
plugin stores this XHTML byte-for-byte in :class:`RawDocument` (format
``"html"``) and only flattens to plain text when the harvest manifest
needs a lossy snippet for filter decisions and the Phase-2 compiler
needs a baseline indexable body.

ATL-12 implements :func:`html_to_plain_text` using ``beautifulsoup4``
with ``'html.parser'`` (no ``lxml`` dep).  The behaviour is:

- ``<pre>`` / ``<code>`` contents are preserved verbatim (whitespace
  and newlines retained).  Block-level newline injection is skipped
  inside these tags so internal indentation survives.
- Block-level tags (``<p>``, ``<div>``, ``<li>``, ``<tr>``, ``<h1>``
  through ``<h6>``) become newline-separated.
- ``<br>`` becomes ``\\n``.
- ``<script>`` / ``<style>`` are stripped entirely.
- Confluence macros: ``<ac:structured-macro>`` and ``<ac:rich-text-body>``
  are treated as transparent wrappers -- their inner prose / code bodies
  survive.  ``<ac:parameter>`` (macro config like ``language=python``)
  is dropped outright because its value is noise for plain-text consumers.
- Runs of three or more consecutive newlines are collapsed to two.
- HTML entities (``&amp;``, ``&lt;``, ``&quot;``, ...) are decoded
  automatically by bs4.
- Malformed / partial XHTML is handled gracefully by the permissive
  ``html.parser`` backend -- no exception is raised.
- Empty / ``None``-equivalent input returns ``""``.

Leading/trailing *newlines* are trimmed from the final string but
leading/trailing *spaces* are preserved so that standalone ``<pre>``
blocks retain their indentation.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString

# Block-level tags whose closing boundary should emit a newline in the
# flattened output.  We deliberately omit ``<pre>`` and ``<code>`` here
# -- their contents are preserved verbatim, and any child block tags
# inside them are also skipped (see ``_inside_verbatim``).
_BLOCK_TAGS = frozenset(
    {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
)

# Tags whose entire subtree must be removed before flattening.
# ``ac:parameter`` carries Confluence macro configuration (language,
# title, severity, ...) which is never user-facing prose.
_DROP_TAGS = ("script", "style", "ac:parameter")

# Verbatim tags: any block-newline injection for descendants of these
# is skipped so internal whitespace / indentation is preserved.
_VERBATIM_TAGS = frozenset({"pre", "code"})

# Collapse 3+ consecutive newlines down to 2.
_BLANK_LINE_RUN = re.compile(r"\n{3,}")


def _inside_verbatim(tag) -> bool:
    """Return True if *tag* has a ``<pre>`` or ``<code>`` ancestor."""
    for parent in tag.parents:
        if parent.name in _VERBATIM_TAGS:
            return True
    return False


def html_to_plain_text(xhtml: str) -> str:
    """Flatten Confluence storage-format XHTML into a plain text string.

    See the module docstring for the full contract.  This function never
    raises on malformed input -- it returns the best-effort text that
    :mod:`html.parser` can recover.
    """
    if not xhtml:
        return ""

    soup = BeautifulSoup(xhtml, "html.parser")

    # 1. Remove tags whose contents must be dropped entirely.
    for tag in soup(list(_DROP_TAGS)):
        tag.decompose()

    # 2. Convert <br> to a literal newline text node.
    for br in soup.find_all("br"):
        br.replace_with(NavigableString("\n"))

    # 3. Append a newline after every block-level tag, except where
    #    the tag (or an ancestor) is inside a verbatim <pre>/<code>
    #    block.  We collect first to avoid mutating-while-iterating.
    block_tags = [
        t
        for t in soup.find_all(True)
        if t.name in _BLOCK_TAGS and not _inside_verbatim(t)
    ]
    for tag in block_tags:
        tag.append(NavigableString("\n"))

    # 4. Flatten.  No separator -- block boundaries are already marked
    #    by the explicit ``\n`` text nodes above, and using a separator
    #    would split inline children (e.g. ``<p>a<span>b</span>c</p>``)
    #    into ``a\nb\nc`` which we do not want.
    text = soup.get_text()

    # 5. Normalise excessive blank-line runs.
    text = _BLANK_LINE_RUN.sub("\n\n", text)

    # 6. Trim outer newlines only.  We intentionally keep leading and
    #    trailing spaces so that a bare ``<pre>  indented</pre>`` input
    #    still round-trips its indentation.
    return text.strip("\n")
