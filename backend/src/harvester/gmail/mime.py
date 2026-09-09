"""MIME → markdown for Gmail message payloads.

Gmail message bodies are wrapped in a recursive MIME tree:

    payload
    ├── headers
    ├── body                        ← present for single-part messages
    └── parts                       ← present for multipart
        ├── { mimeType: text/plain, body: { data: <base64url> } }
        ├── { mimeType: text/html,  body: { data: <base64url> } }
        └── { mimeType: image/png,  body: { attachmentId: ... } }   ← inline

The harvester wants a clean, markdown-friendly text body. Strategy:

1. Walk the tree and pick the best textual part. Prefer ``text/plain``;
   fall back to ``text/html`` when no plaintext exists. Multipart/alternative
   chooses plain over HTML; multipart/related chooses the root-document
   branch.
2. Decode the chosen part's ``body.data`` (base64url) using the part's
   ``charset`` parameter (default UTF-8).
3. If the chosen part is HTML, run it through ``markdownify``. Otherwise
   keep the plaintext as-is.
4. Append a list of attachment placeholders so the LLM sees that
   non-text parts existed even though we don't inline their bytes.

The Confluence normalizer plays the same role for XHTML — see
:mod:`src.harvester.confluence.normalizer`.
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Iterable

import markdownify

logger = logging.getLogger(__name__)

_PLAINTEXT_MIME = "text/plain"
_HTML_MIME = "text/html"


def _decode_body(part: dict) -> str:
    """Decode a MIME part's ``body.data`` to a Python ``str``.

    Returns ``""`` when the part is empty / has no inline data (e.g.
    parts whose body is referenced by ``attachmentId`` only).
    """
    body = part.get("body") or {}
    data = body.get("data")
    if not data:
        return ""
    try:
        raw = base64.urlsafe_b64decode(data.encode("ascii"))
    except Exception:  # noqa: BLE001 — corrupt fixtures shouldn't crash a harvest
        logger.debug("Gmail body base64 decode failed", exc_info=True)
        return ""
    charset = _charset_for(part) or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def _charset_for(part: dict) -> str | None:
    """Extract the ``charset`` parameter from a part's ``Content-Type``.

    Gmail surfaces this two ways: as a parsed parameter on the part's
    ``body`` (rare, depends on format) and as a header on the part's
    headers list. Check the headers — that's the canonical location.
    """
    headers = part.get("headers") or []
    for h in headers:
        if (h.get("name") or "").lower() == "content-type":
            value = h.get("value") or ""
            match = re.search(r"charset\s*=\s*\"?([A-Za-z0-9._-]+)\"?", value)
            if match:
                return match.group(1)
    return None


def _walk_parts(payload: dict) -> Iterable[dict]:
    """Yield the root payload then every nested part, depth-first."""
    if not payload:
        return
    yield payload
    for child in payload.get("parts") or ():
        yield from _walk_parts(child)


def extract_text_part(payload: dict) -> tuple[str, str]:
    """Return ``(mime_type, decoded_body)`` for the best text part.

    Walks the tree once, recording the first text/plain and text/html
    parts encountered (depth-first). Plaintext wins over HTML; if
    neither is present, returns ``("", "")``.
    """
    plain_body: str | None = None
    html_body: str | None = None

    for part in _walk_parts(payload):
        mime = (part.get("mimeType") or "").lower()
        if mime == _PLAINTEXT_MIME and plain_body is None:
            plain_body = _decode_body(part)
        elif mime == _HTML_MIME and html_body is None:
            html_body = _decode_body(part)

    if plain_body:
        return (_PLAINTEXT_MIME, plain_body)
    if html_body:
        return (_HTML_MIME, html_body)
    return ("", "")


def _attachment_placeholders(payload: dict) -> list[str]:
    """Render ``[attachment: filename.ext]`` lines for inline attachments.

    Listed in tree order so a reader can correlate them with the body
    above. Filenames are best-effort — Gmail occasionally omits the
    ``filename`` field for inline images and we keep the placeholder
    rather than skip silently.
    """
    placeholders: list[str] = []
    for part in _walk_parts(payload):
        body = part.get("body") or {}
        if body.get("attachmentId"):
            filename = part.get("filename") or "(unnamed)"
            placeholders.append(f"[attachment: {filename}]")
    return placeholders


def mime_to_markdown(payload: dict) -> str:
    """Convert a Gmail message ``payload`` to clean markdown body.

    Returns ``""`` when the payload has no textual content. The output
    has a trailing newline only if attachments are appended; the caller
    is responsible for joining message bodies into the per-thread
    document.
    """
    mime_type, body = extract_text_part(payload)
    text: str
    if mime_type == _HTML_MIME:
        try:
            text = markdownify.markdownify(body, heading_style="ATX")
        except Exception:  # noqa: BLE001 — fall back to raw HTML on conversion failure
            logger.exception("Gmail HTML→markdown conversion failed")
            text = body
    else:
        text = body

    text = text.strip("\n")

    placeholders = _attachment_placeholders(payload)
    if placeholders:
        if text:
            text = text + "\n\n" + "\n".join(placeholders)
        else:
            text = "\n".join(placeholders)

    # Collapse runs of 3+ blank lines — markdownify can produce them
    # from nested HTML.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text
