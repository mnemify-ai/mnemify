"""Confluence source plugin — implements :class:`SourcePlugin`.

Maps the Confluence REST API onto the common ``SourcePlugin`` contract so
the harvest orchestrator can treat Confluence like Notion or Obsidian.

Design decisions from 2026-04-19:

- ``RawDocument.content`` is the page's ``body.storage.value`` XHTML
  encoded as UTF-8 bytes — stored **as-is**, no HTML→MD conversion,
  no truncation.  ``RawDocument.format == "html"``.
- ``RawDocument.metadata`` carries the §3.1 keys: ``document_type``,
  ``url``, ``space_key``, ``version_number``, ``author_id``,
  ``author_name``, ``created_at``, ``updated_at``, ``parent_id``,
  ``parent_title``, ``ancestors``, ``labels``, ``attachment_count``.
- ``DocRef.metadata`` at list-time is the §3.1 subset — everything
  that's cheap from the list endpoint, omitting anything that needs
  a full-page fetch.
- ``fetch_attachment`` (ATL-30) delegates to
  :meth:`ConfluenceClient.download_attachment_content`, which reuses
  the ``atlassian-python-api`` session's basic-auth credentials and
  runs under the same tenacity retry harness as the REST methods.
  ``RawDocument.attachments`` is populated by ``fetch_document`` so
  the orchestrator can drive the download loop.
- ``mark_harvested`` and ``aclose`` are no-ops: no write-back to
  Confluence in Phase 1, and ``atlassian-python-api`` is synchronous
  with no pooled resources to close.
"""

from __future__ import annotations

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
from .client import ConfluenceAPIError, ConfluenceAuthError, ConfluenceClient
from .models import ConfluenceConfig
from .normalizer import confluence_to_markdown
from .pages import PageExtractor
# Bind the classmethod at import time so that test patches of
# ``PageExtractor`` in this module (see ``tests/test_confluence_plugin.py``)
# do not accidentally mock the ancestor-extraction helper — the real
# implementation is a pure static function and is safe to call directly.
_extract_ancestor_chain = PageExtractor._extract_ancestor_chain

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────


def _parse_iso(raw: str | None) -> datetime | None:
    """Parse a Confluence ISO-8601 timestamp into an aware UTC datetime.

    Returns ``None`` on missing / unparseable input rather than raising —
    timestamp metadata is informative, not a correctness-critical field.
    """
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        logger.debug("Unparseable Confluence timestamp: %r", raw)
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_or_none(dt: datetime | None) -> str | None:
    """Serialise a datetime to ISO-8601 with ``Z`` suffix, or ``None``."""
    if dt is None:
        return None
    # ``datetime.isoformat`` emits ``+00:00``; normalise to ``Z`` for
    # parity with the raw Confluence payload formatting.
    return dt.isoformat().replace("+00:00", "Z")


def _absolute_web_url(base_url: str, webui_suffix: str | None) -> str | None:
    """Join ``base_url`` with a ``_links.webui`` relative path."""
    if not webui_suffix:
        return None
    if webui_suffix.startswith("http://") or webui_suffix.startswith("https://"):
        return webui_suffix
    return f"{base_url.rstrip('/')}{webui_suffix}"


def _absolute_download_url(
    base_url: str, parent_page_id: str, attachment: dict
) -> str | None:
    """Resolve an authenticated download URL for an attachment.

    Returns a REST-API content download URL of the form
    ``{base_url}/rest/api/content/{pageId}/child/attachment/{attId}/download``.
    The legacy ``/wiki/download/attachments/...`` path that Confluence
    surfaces in ``_links.download`` rejects ``email + API token`` basic
    auth (``www-authenticate: OAuth``) regardless of token scope; the
    REST API path honours basic auth and 302-redirects to the signed
    media CDN URL, which our caller follows transparently.

    Falls back to passing through ``_links.download`` verbatim when it
    is already an absolute external URL (some tenants return signed
    CDN links directly). Returns ``None`` — signalling "drop this
    attachment" — when the attachment has no ``id`` or no
    ``_links.download``.
    """
    links = attachment.get("_links") or {}
    download = links.get("download")
    if not download:
        return None
    if download.startswith("http://") or download.startswith("https://"):
        return download
    att_id = attachment.get("id")
    if not att_id:
        return None
    return (
        f"{base_url.rstrip('/')}/rest/api/content/"
        f"{parent_page_id}/child/attachment/{att_id}/download"
    )


def _extensions_file_size(attachment: dict) -> int | None:
    """Pull an attachment's file size from ``extensions.fileSize`` if present."""
    extensions = attachment.get("extensions") or {}
    raw = extensions.get("fileSize")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# ── Plugin ────────────────────────────────────────────────────────


class ConfluenceHarvesterPlugin(SourcePlugin):
    """Confluence implementation of :class:`SourcePlugin`.

    The factory in ``src/harvester/confluence/__init__.py`` resolves
    the ``email`` / ``token`` env vars and passes them in; a direct
    instantiation path (``email=""``/``token=""``) is still supported
    for tests that mock the client.
    """

    SOURCE_TYPE = "confluence"

    def __init__(
        self,
        config: ConfluenceConfig,
        *,
        email: str = "",
        token: str = "",
    ) -> None:
        self.config = config
        self.client = ConfluenceClient(
            base_url=config.base_url,
            email=email,
            token=token,
        )
        self.pages = PageExtractor(self.client)

    # ── SourcePlugin interface ─────────────────────────────────────

    async def test_connection(self) -> HealthStatus:
        """Verify the Confluence API credentials work.

        Calls the cheap ``/rest/api/space`` endpoint with ``limit=1`` —
        a 2xx means the basic-auth header resolved.  Auth failures are
        translated into an unhealthy ``HealthStatus`` with a remediation
        hint naming the env vars the user needs to fix.
        """
        try:
            envelope = await self.client.list_spaces(limit=1)
        except ConfluenceAuthError as exc:
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=(
                    f"Confluence auth failed: {exc}.  Check "
                    f"{self.config.email_env!r} and {self.config.token_env!r} "
                    "environment variables."
                ),
            )
        except ConfluenceAPIError as exc:
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=f"Confluence API error: {exc}",
            )
        except Exception as exc:  # pragma: no cover — defensive
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=f"Confluence connection failed: {exc}",
            )

        results = envelope.get("results", []) if envelope else []
        space_count = len(results)
        return HealthStatus(
            healthy=True,
            source_type=self.SOURCE_TYPE,
            message=(
                f"Connected to {self.config.base_url} "
                f"({space_count} space{'s' if space_count != 1 else ''} visible)"
            ),
            details={"base_url": self.config.base_url},
        )

    async def list_documents(self, since: datetime | None = None) -> list[DocRef]:
        """Enumerate pages across ``config.space_keys`` + ``config.page_ids``.

        ``space_keys`` harvest whole spaces; each entry in ``page_ids``
        harvests that page plus its descendant subtree.  Results are
        deduped by page id (a page can appear both under a selected space
        and under a selected ancestor page).  Populates ``DocRef.metadata``
        with the subset of §3.1 keys available at list time — anything
        requiring a full-page fetch (body, ancestors, labels, attachment
        count) is deferred to :meth:`fetch_document`.
        """
        logger.debug(
            "ConfluenceHarvesterPlugin.list_documents: spaces=%s pages=%s since=%s",
            self.config.space_keys,
            self.config.page_ids,
            since,
        )
        results: list[DocRef] = []
        seen: set[str] = set()
        async for page in self.pages.list_pages(self.config.space_keys, since=since):
            doc_ref = self._doc_ref_from_list_page(page)
            if doc_ref is None or doc_ref.source_id in seen:
                continue
            seen.add(doc_ref.source_id)
            results.append(doc_ref)

        for root_id in self.config.page_ids:
            try:
                async for page in self.pages.list_pages_under(str(root_id)):
                    doc_ref = self._doc_ref_from_list_page(
                        page, origin_scope_id=str(root_id)
                    )
                    if doc_ref is None or doc_ref.source_id in seen:
                        continue
                    seen.add(doc_ref.source_id)
                    results.append(doc_ref)
            except ConfluenceAuthError:
                raise
            except ConfluenceAPIError as exc:
                # A stale scope id (page deleted / permissions revoked)
                # shouldn't sink the whole run — the configured spaces and
                # remaining subtrees still harvest.
                logger.warning(
                    "Confluence page-scope root %s could not be listed, "
                    "skipping its subtree: %s",
                    root_id,
                    exc,
                )

        logger.debug(
            "ConfluenceHarvesterPlugin.list_documents: %d pages returned", len(results)
        )
        return results

    async def fetch_document(self, doc_ref: DocRef) -> RawDocument:
        """Fetch one page and package it as :class:`RawDocument`.

        Body is stored byte-for-byte in ``content`` (XHTML, UTF-8).
        Attachment *refs* (not bytes) are attached so the orchestrator
        can drive the download loop.  The download pathway itself
        (:meth:`fetch_attachment`) is Phase 1d (ATL-30).
        """
        page_id = doc_ref.source_id
        logger.debug("ConfluenceHarvesterPlugin.fetch_document: page_id=%s", page_id)

        page = await self.pages.get_full_page(page_id)
        attachments_raw = await self.pages.list_page_attachments(page_id)

        body_xhtml = (
            (page.get("body") or {}).get("storage", {}).get("value", "")
        ) or ""
        content = body_xhtml.encode("utf-8")

        ancestors = _extract_ancestor_chain(page)
        parent = ancestors[-1] if ancestors else None

        version = page.get("version") or {}
        history = page.get("history") or {}
        created_by = history.get("createdBy") or {}
        labels_meta = (
            (page.get("metadata") or {}).get("labels") or {}
        )
        label_results = labels_meta.get("results") if isinstance(labels_meta, dict) else None
        labels = [
            lbl.get("name")
            for lbl in (label_results or [])
            if isinstance(lbl, dict) and lbl.get("name")
        ]

        webui_suffix = (page.get("_links") or {}).get("webui")
        url = _absolute_web_url(self.config.base_url, webui_suffix)

        created_at = _parse_iso(history.get("createdDate"))
        updated_at = _parse_iso(version.get("when"))

        att_refs = self._attachment_refs(page_id, attachments_raw)

        metadata = {
            "document_type": "page",
            "url": url,
            "space_key": (page.get("space") or {}).get("key") or self._space_key_from_ancestors(page),
            "version_number": version.get("number"),
            "author_id": created_by.get("accountId"),
            "author_name": created_by.get("displayName") or created_by.get("publicName"),
            # The *last* editor (version.by) — distinct from the original
            # author when teammates edit the page after creation.
            "last_modified_by": (
                (version.get("by") or {}).get("displayName")
                or (version.get("by") or {}).get("publicName")
            ),
            "last_modified_by_id": (version.get("by") or {}).get("accountId"),
            "version_message": version.get("message") or None,
            "created_at": _iso_or_none(created_at),
            "updated_at": _iso_or_none(updated_at),
            "parent_id": parent["id"] if parent else None,
            "parent_title": parent["title"] if parent else None,
            "ancestors": ancestors,
            "labels": labels,
            "attachment_count": len(att_refs),
        }

        title = page.get("title") or doc_ref.title or ""
        return RawDocument(
            source_id=page_id,
            title=title,
            content=content,
            format="html",
            metadata=metadata,
            attachments=att_refs,
        )

    async def fetch_attachment(self, att_ref: AttachmentRef) -> bytes:
        """Download an attachment via the authenticated Atlassian client.

        Delegates to :meth:`ConfluenceClient.download_attachment_content`,
        which reuses the ``atlassian-python-api`` client's
        ``requests.Session`` (already carrying our basic-auth credentials)
        and runs under the same tenacity retry harness as every other
        REST method — 429/5xx are retried with ``Retry-After``-aware
        backoff; 401/403 surface as :class:`ConfluenceAuthError`; other
        4xx surface as :class:`ConfluenceAPIError`.

        The URL is the REST API content-download path
        (``*.atlassian.net/wiki/rest/api/content/{pageId}/child/attachment/{attId}/download``)
        the plugin already wrote into ``att_ref.url`` when it built the
        ref from ``/content/{id}/child/attachment``.  The orchestrator
        (``src/harvester/orchestrator.py:307-352``) owns the downstream
        write to ``{raw}/confluence/{id[:2]}/{id}/attachments/...`` and
        the manifest update; this method's contract is "bytes out".
        """
        return await self.client.download_attachment_content(att_ref.url)

    def normalize(self, raw: RawDocument) -> NormalizedDocument:
        """Convert Confluence XHTML storage format to clean markdown.

        Calls :func:`confluence_to_markdown` with the raw XHTML body.
        The output is pure markdown — no frontmatter. All structured
        metadata (url, space_key, labels, etc.) lives in the manifest's
        ``documents.metadata`` JSON column, not in the .md file.
        """
        xhtml = raw.content.decode("utf-8", errors="replace")
        markdown = confluence_to_markdown(
            xhtml,
            raw.metadata,
            base_url=self.config.base_url,
        )
        return NormalizedDocument(
            source_id=raw.source_id,
            title=raw.title,
            markdown=markdown,
            frontmatter={},
            normalizer_version="0.2.0",
        )

    async def aclose(self) -> None:
        """Release client-owned resources (currently none).

        :class:`ConfluenceClient` wraps ``atlassian-python-api`` which
        is synchronous and has no pooled resources to close.  The
        ``aclose`` symmetry matters because other plugins (e.g. Notion)
        carry HTTP clients — the orchestrator awaits this uniformly.
        """
        await self.client.aclose()

    # ── Internal helpers ──────────────────────────────────────────

    def _doc_ref_from_list_page(
        self, page: dict, origin_scope_id: str | None = None
    ) -> DocRef | None:
        """Project a list-endpoint page dict into a :class:`DocRef`.

        Skips pages without an ``id`` — without a stable ID they
        cannot be re-fetched and have no place in the manifest.
        Applies the ``include_archived`` policy: when False (default),
        pages whose status is ``"archived"`` are dropped.

        ``origin_scope_id`` overrides the scope-aware-deletion origin tag:
        pages reached through a ``page_ids`` subtree are stamped with the
        selected root page id, not their space key, so removing that root
        from Manage Scope later marks exactly its subtree out-of-scope.
        """
        page_id = page.get("id")
        if not page_id:
            logger.warning("Confluence list entry missing 'id', skipping: %r", page)
            return None

        status = page.get("status")
        if not self.config.include_archived and status == "archived":
            return None

        version = page.get("version") or {}
        modified_at = _parse_iso(version.get("when"))
        version_by = version.get("by") or {}

        webui_suffix = (page.get("_links") or {}).get("webui")
        source_url = _absolute_web_url(self.config.base_url, webui_suffix)

        space_key = (page.get("space") or {}).get("key")
        title = page.get("title") or ""

        metadata = {
            "document_type": "page",
            "url": source_url,
            "space_key": space_key,
            "updated_at": _iso_or_none(modified_at),
            "last_modified_by": version_by.get("displayName") or version_by.get("publicName"),
            "last_modified_by_id": version_by.get("accountId"),
            "status": status,
            # Scope-aware deletion (Option B): the origin is the unit the
            # user picks in Manage Scope — the space key for whole-space
            # scope, or the selected root page id for page-subtree scope.
            "origin_scope_id": origin_scope_id if origin_scope_id is not None else space_key,
        }

        return DocRef(
            source_id=str(page_id),
            title=title,
            source_type=self.SOURCE_TYPE,
            source_url=source_url,
            modified_at=modified_at,
            metadata=metadata,
        )

    def _attachment_refs(
        self,
        parent_page_id: str,
        attachments_raw: list[dict],
    ) -> list[AttachmentRef]:
        """Convert raw Confluence attachment dicts into :class:`AttachmentRef`.

        ``AttachmentRef.source_id`` is the *parent page* id so the
        orchestrator's sharding layout (``{raw}/confluence/{parent[:2]}/{parent}/...``)
        places every attachment under its owning page.  Dropped:
        attachments missing a resolvable download URL — they cannot be
        fetched by :meth:`fetch_attachment`.
        """
        refs: list[AttachmentRef] = []
        for att in attachments_raw:
            if not isinstance(att, dict):
                continue
            url = _absolute_download_url(self.config.base_url, parent_page_id, att)
            if not url:
                logger.debug(
                    "Confluence attachment missing download URL, skipping: %r",
                    att.get("id") or att.get("title"),
                )
                continue
            filename = att.get("title") or att.get("id") or "attachment"
            mime_type = (
                (att.get("extensions") or {}).get("mediaType")
                or (att.get("metadata") or {}).get("mediaType")
            )
            refs.append(
                AttachmentRef(
                    source_id=parent_page_id,
                    filename=filename,
                    url=url,
                    mime_type=mime_type,
                    size=_extensions_file_size(att),
                )
            )
        return refs

    @staticmethod
    def _space_key_from_ancestors(page: dict) -> str | None:
        """Last-resort space-key recovery when ``space`` is absent.

        Some list-endpoint responses omit ``space`` when it's implied
        by the query.  In practice the plan doc §3.1 requires a
        ``space_key`` field, so we fall back to reading it off the
        deepest ancestor where present.  Returns ``None`` if nothing
        is available — the orchestrator will still see the page, just
        without a space tag.
        """
        for ancestor in reversed(page.get("ancestors") or []):
            if isinstance(ancestor, dict):
                sp = (ancestor.get("space") or {}).get("key")
                if sp:
                    return sp
        return None
