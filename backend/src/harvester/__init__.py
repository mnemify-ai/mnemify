"""Mnemify Harvester — plugin interface and shared types.

SourcePlugin is the base class every source connector (Notion, Confluence, etc.)
must implement. The harvest orchestrator calls these methods without knowing
which source it's talking to.

DocRef, RawDocument, AttachmentRef, and HealthStatus are the shared data types
that flow between plugins and the orchestrator.
"""

from __future__ import annotations

import contextvars
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

# ── Per-document extraction-warning capture ─────────────────────────
#
# Connectors drop pieces of a document's content during extraction —
# Notion blocks the API can't serialize, ADF node types with no handler,
# minimized GitHub comments, and so on. Historically each drop was a
# ``logger.warning`` nobody read. This collector turns those drops into a
# structured, per-run statistic that the orchestrator folds into
# ``HarvestResult.warnings`` and surfaces on ``/api/harvest/current``.
#
# The active collector is a per-document list installed by the orchestrator
# around each fetch. Because each document is fetched in its own asyncio task
# (and Notion's renderer runs under ``asyncio.to_thread``, which propagates
# the context), the var gives us per-document *and* per-source attribution for
# free — with one rule, enforced by ``report_extraction_warning`` below: deep
# or threaded code must ``.append`` to the existing list, never ``.set`` a new
# one (a ``set`` inside the worker thread is stranded in that thread's context
# copy and lost).
_extraction_warnings: contextvars.ContextVar[list[tuple[str, str]] | None] = (
    contextvars.ContextVar("mnemify_extraction_warnings", default=None)
)


def report_extraction_warning(kind: str, detail: str = "") -> None:
    """Record that a piece of the current document's content was dropped.

    ``kind`` is a stable machine slug (e.g. ``"notion_unsupported_block"``);
    ``detail`` is a short free-form qualifier (e.g. the dropped block type).
    Outside a harvest — no collector installed, e.g. during ``list_documents``
    — this is a no-op, so connectors may call it unconditionally.
    """
    bucket = _extraction_warnings.get()
    if bucket is not None:
        bucket.append((kind, detail))


def begin_extraction_capture() -> contextvars.Token:
    """Install a fresh per-document warning collector; returns a reset token.

    The orchestrator wraps each document fetch in
    ``begin_extraction_capture`` → ``take_extraction_warnings`` →
    ``reset_extraction_capture``.
    """
    return _extraction_warnings.set([])


def take_extraction_warnings() -> list[tuple[str, str]]:
    """Return warnings collected since the last ``begin_extraction_capture``."""
    return list(_extraction_warnings.get() or [])


def reset_extraction_capture(token: contextvars.Token) -> None:
    """Tear down the collector installed by ``begin_extraction_capture``."""
    _extraction_warnings.reset(token)


@dataclass
class DocRef:
    """Lightweight reference to a document — no content, just metadata for filtering."""

    source_id: str
    title: str
    source_type: str
    source_url: str | None = None
    modified_at: datetime | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class RawDocument:
    """A fetched document with its content in native format."""

    source_id: str
    title: str
    content: bytes  # Raw content in native format (JSON, XML, MD, etc.)
    format: str  # "json" | "xml" | "md" | "html"
    metadata: dict = field(default_factory=dict)
    attachments: list[AttachmentRef] = field(default_factory=list)


@dataclass
class NormalizedDocument:
    """A cleaned document ready for downstream tiers.

    Produced by ``SourcePlugin.normalize(raw)``. The ``markdown`` field
    carries the clean body written to
    ``{normalized_root}/{source_type}/{shard}/{source_id}.md``. Per the
    harvester contract, the body is pure text — no YAML frontmatter, no
    metadata headers — so the .md file is directly usable as LLM input.
    Structured metadata lives in the harvest manifest
    (``documents.metadata`` JSON column), not in the file.

    ``frontmatter`` is retained as an optional structured-metadata channel
    for plugins that haven't migrated to the no-frontmatter contract
    (Jira, Obsidian). Confluence and Notion leave it empty.
    """

    source_id: str
    title: str
    markdown: str
    frontmatter: dict = field(default_factory=dict)
    normalizer_version: str = "0.1.0"


@dataclass
class AttachmentRef:
    """Reference to a downloadable attachment.

    The ``url`` field holds a web URL for network-fetched sources (e.g. a
    Notion CDN link) or a local filesystem path for file-based sources (e.g.
    an Obsidian vault attachment).  The source plugin's ``fetch_attachment()``
    is the only consumer of this field, so the interpretation is
    plugin-specific.
    """

    source_id: str
    filename: str
    url: str
    mime_type: str | None = None
    size: int | None = None


@dataclass
class HealthStatus:
    """Health check result for a source."""

    healthy: bool
    source_type: str
    message: str
    details: dict = field(default_factory=dict)


class SourcePlugin(ABC):
    """Base class all source plugins must implement."""

    @abstractmethod
    async def test_connection(self) -> HealthStatus:
        """Verify auth and connectivity."""
        ...

    @abstractmethod
    async def list_documents(self, since: datetime | None = None) -> list[DocRef]:
        """List available documents, optionally filtered by modification time."""
        ...

    @abstractmethod
    async def fetch_document(self, doc_ref: DocRef) -> RawDocument:
        """Fetch full content in native format."""
        ...

    @abstractmethod
    async def fetch_attachment(self, att_ref: AttachmentRef) -> bytes:
        """Download a single attachment."""
        ...

    def normalize(self, raw: RawDocument) -> NormalizedDocument:
        """Convert ``raw`` into a clean markdown artifact for the compiler.

        Default is a byte-passthrough suitable for sources whose raw format
        is already markdown (Obsidian). Each source plugin should override
        with its own converter:

        - Confluence: XHTML storage format → markdown via ``markdownify`` +
          custom macro handlers.
        - Jira: JSON envelope → markdown via ADF walker.
        - Notion: raises ``NotImplementedError`` — the compiler reader's
          Notion JSON branch remains the primary path because the envelope
          carries both pre-rendered markdown and a block tree used for
          edge mining.
        """
        md = raw.content.decode("utf-8", errors="replace")
        return NormalizedDocument(
            source_id=raw.source_id,
            title=raw.title,
            markdown=md,
            frontmatter={},
            normalizer_version="0.1.0-passthrough",
        )

    async def mark_harvested(
        self,
        source_id: str,
        timestamp: str,
        property_name: str = "",
    ) -> None:
        """Optional: write harvest timestamp back to source. Default: no-op.

        Override in plugins that support write-back (e.g. Notion date
        properties).  File-based plugins (e.g. Obsidian) inherit this no-op
        — user vault files are never modified by the harvester.
        """

    async def aclose(self) -> None:
        """Release plugin-owned resources (network clients, file handles).

        Override in plugins that hold long-lived connections.  The default
        is a no-op so that simple, stateless plugins (e.g. Obsidian) don't
        need to implement cleanup.
        """
