"""Gmail source plugin — implements :class:`SourcePlugin` for the harvester.

Mirrors :class:`src.harvester.jira.plugin.JiraHarvesterPlugin` in shape:

- ``test_connection`` probes ``users.getProfile`` (cheapest auth call).
- ``list_documents`` enumerates threads via the search query built from
  the configured filters; emits one :class:`DocRef` per thread.
- ``fetch_document`` retrieves a thread in full and returns a
  :class:`RawDocument` with ``format="json"`` carrying the raw thread
  envelope as UTF-8 bytes — the orchestrator persists it under
  ``{raw_root}/gmail/<shard>/<thread_id>.json``.
- ``fetch_attachment`` downloads a single attachment via a synthetic
  compound URL ``"<message_id>/<attachment_id>"`` carried on the
  :class:`AttachmentRef`.
- ``normalize`` returns pure-body markdown; ``frontmatter={}``. All
  metadata flows through ``RawDocument.metadata`` to the manifest.

``mark_harvested`` is a deliberate no-op — read-only scope means we
cannot write back, and the harvester never modifies the source mailbox.
``aclose`` delegates to :class:`GmailClient.aclose`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from src.harvester import (
    AttachmentRef,
    DocRef,
    HealthStatus,
    NormalizedDocument,
    RawDocument,
    SourcePlugin,
)

from .client import GmailAPIError, GmailAuthError, GmailClient
from .fields import flatten_thread_fields
from .mime import _walk_parts as _walk_payload_parts
from .models import GmailConfig
from .normalizer import gmail_to_markdown
from .query import build_query
from .threads import ThreadExtractor

logger = logging.getLogger(__name__)


def _internal_date_to_dt(internal_date) -> datetime | None:
    """Parse Gmail's ``internalDate`` (ms since epoch) into a naive-UTC datetime.

    Returns ``None`` on missing / malformed input. Naive-UTC matches the
    other plugins' :class:`DocRef.modified_at` convention.
    """
    if internal_date is None:
        return None
    try:
        ms = int(internal_date)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).replace(tzinfo=None)


class GmailHarvesterPlugin(SourcePlugin):
    """Gmail implementation of the :class:`SourcePlugin` interface."""

    SOURCE_TYPE = "gmail"

    def __init__(
        self,
        config: GmailConfig,
        *,
        client: GmailClient | None = None,
    ) -> None:
        self.config = config
        if client is None:
            # Tests / smoke construction without OAuth — every network
            # call will fail, but the contract assertions don't need it.
            client = GmailClient(
                credentials_path="",
                token_path="",
                user_id=config.user_id,
            )
        self.client = client
        self.threads = ThreadExtractor(self.client)

    # ── SourcePlugin interface ─────────────────────────────────────

    async def test_connection(self) -> HealthStatus:
        """Probe ``users.getProfile`` to verify the OAuth credentials work."""
        try:
            profile = await self.client.get_profile()
        except GmailAuthError as exc:
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=(
                    f"Gmail authentication failed ({exc.status_code}). "
                    "Re-run `mnemify login --source gmail` to refresh the OAuth token."
                ),
            )
        except GmailAPIError as exc:
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=f"Gmail API error: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 — probe must not raise
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=f"Connection failed: {exc}",
            )

        email = profile.get("emailAddress") or "unknown"
        return HealthStatus(
            healthy=True,
            source_type=self.SOURCE_TYPE,
            message=f"Connected as {email}",
            details={
                "emailAddress": email,
                "messagesTotal": profile.get("messagesTotal"),
                "threadsTotal": profile.get("threadsTotal"),
            },
        )

    async def list_documents(self, since: datetime | None = None) -> list[DocRef]:
        """Enumerate threads matching the configured filters as :class:`DocRef`.

        FIXME(scope-aware-since): the orchestrator currently passes
        ``since=None``. Gmail uses ``since`` server-side via
        ``after:{epoch}``, so disabling it forces a full-mailbox enumeration
        every run. Acceptable while this plugin is unwired; revisit with a
        scope-aware approach (compare current label_filter / sender_allowlist
        against the per-run scope recorded in the manifest) when it's wired
        into the UI.
        """
        query = build_query(
            since=since,
            label_filter=self.config.label_filter,
            label_exclude=self.config.label_exclude,
            sender_allowlist=self.config.sender_allowlist,
        )

        doc_refs: list[DocRef] = []
        async for stub in self.threads.list_threads(
            query=query,
            max_threads=self.config.max_threads_per_run,
        ):
            thread_id = stub.get("id")
            if not thread_id:
                continue
            doc_refs.append(
                DocRef(
                    source_id=thread_id,
                    title=stub.get("snippet") or "",
                    source_type=self.SOURCE_TYPE,
                    source_url=None,  # Full URL set on RawDocument.metadata
                    modified_at=None,  # internalDate not present on stubs; set on fetch
                    metadata={"document_type": "thread"},
                )
            )
        return doc_refs

    async def fetch_document(self, doc_ref: DocRef) -> RawDocument:
        """Fetch a thread's full content as :class:`RawDocument` (format='json')."""
        thread = await self.threads.get_full_thread(doc_ref.source_id)
        content = json.dumps(thread, ensure_ascii=False).encode("utf-8")

        metadata = flatten_thread_fields(thread)
        attachments = self._attachment_refs(thread)

        title = metadata.get("subject") or doc_ref.title or "(no subject)"

        return RawDocument(
            source_id=thread.get("id") or doc_ref.source_id,
            title=title,
            content=content,
            format="json",
            metadata=metadata,
            attachments=attachments,
        )

    async def fetch_attachment(self, att_ref: AttachmentRef) -> bytes:
        """Download an attachment using the synthetic compound URL on the ref.

        The ``url`` field encodes ``"{message_id}/{attachment_id}"`` —
        Gmail attachments are addressed by both ids, but
        :class:`AttachmentRef` only carries one URL field, so the plugin
        packs both into it and unpacks here.
        """
        if "/" not in att_ref.url:
            raise ValueError(
                f"Malformed Gmail attachment URL {att_ref.url!r}: expected "
                "'<message_id>/<attachment_id>'"
            )
        message_id, attachment_id = att_ref.url.split("/", 1)
        return await self.client.get_attachment(message_id, attachment_id)

    def normalize(self, raw: RawDocument) -> NormalizedDocument:
        """Convert thread JSON to pure-body markdown — no frontmatter."""
        markdown = gmail_to_markdown(raw.content, raw.metadata)
        return NormalizedDocument(
            source_id=raw.source_id,
            title=raw.title,
            markdown=markdown,
            frontmatter={},
            normalizer_version="0.1.0",
        )

    async def aclose(self) -> None:
        """Release the underlying :class:`GmailClient` (best-effort)."""
        await self.client.aclose()

    # ── Internal helpers ──────────────────────────────────────────

    def _attachment_refs(self, thread: dict) -> list[AttachmentRef]:
        """Build :class:`AttachmentRef` list for every inline attachment in *thread*.

        The synthetic ``url`` packs the message id and attachment id so
        ``fetch_attachment`` can address the part later. ``source_id`` is
        the thread id (matching how the orchestrator shards the on-disk
        attachments directory under the parent document).
        """
        thread_id = thread.get("id") or ""
        refs: list[AttachmentRef] = []
        for msg in thread.get("messages") or ():
            message_id = msg.get("id") or ""
            payload = msg.get("payload") or {}
            for part in _walk_payload_parts(payload):
                body = part.get("body") or {}
                attachment_id = body.get("attachmentId")
                if not attachment_id or not message_id:
                    continue
                filename = part.get("filename") or "(unnamed)"
                size = body.get("size")
                if not isinstance(size, int):
                    size = None
                refs.append(
                    AttachmentRef(
                        source_id=thread_id,
                        filename=filename,
                        url=f"{message_id}/{attachment_id}",
                        mime_type=part.get("mimeType"),
                        size=size,
                    )
                )
        return refs
