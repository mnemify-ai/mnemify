"""Text extraction for the local files connector.

Markdown and plain text are already text. PDF goes through ``pypdf``; only
digital PDFs (ones with a text layer) yield anything — a scanned PDF comes
back empty and ``pdf_to_markdown`` raises so the orchestrator records the
document as not normalized instead of compiling a blank page.
"""

from __future__ import annotations

import io
import re

from src.harvester import report_extraction_warning


class NoTextLayerError(ValueError):
    """The PDF has no extractable text (scanned / image-only)."""


def pdf_to_markdown(content: bytes, *, label: str = "") -> str:
    """Extract a PDF's text layer as markdown, one section per page.

    Pages are joined with blank lines; page breaks are kept as a light
    ``---`` rule so the chunker still sees natural boundaries. Encrypted
    PDFs with an empty user password are opened transparently.
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001 — pypdf raises several types here
            report_extraction_warning("pdf_encrypted", label)
            raise NoTextLayerError(f"PDF is encrypted: {label or 'document'}")

    pages: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 — malformed content streams
            text = ""
        text = _tidy(text)
        if text:
            pages.append(text)

    if not pages:
        report_extraction_warning("pdf_no_text", label)
        raise NoTextLayerError(
            f"No text layer in {label or 'PDF'} — scanned PDFs are not supported"
        )
    return "\n\n---\n\n".join(pages).strip() + "\n"


_WS_RUN = re.compile(r"[ \t\f\v]+")
_BLANK_RUN = re.compile(r"\n{3,}")


def _tidy(text: str) -> str:
    """Collapse the ragged whitespace pypdf leaves behind."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(_WS_RUN.sub(" ", line).strip() for line in text.split("\n"))
    return _BLANK_RUN.sub("\n\n", text).strip()
