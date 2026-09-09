"""Notion source plugin — implements SourcePlugin for the harvest orchestrator.

Wraps the low-level Notion extractors (PageExtractor, DatabaseExtractor,
AttachmentExtractor) into the common SourcePlugin interface so the harvest
orchestrator can treat Notion like any other source.

Usage:
    async with NotionClient(token="...") as client:
        plugin = NotionHarvesterPlugin(client)

        health = await plugin.test_connection()
        docs = await plugin.list_documents(since=some_datetime)
        raw = await plugin.fetch_document(docs[0])
        text = plugin.extract_plain_text(raw)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

import httpx

from src.harvester import (
    AttachmentRef,
    DocRef,
    HealthStatus,
    NormalizedDocument,
    RawDocument,
    SourcePlugin,
)
from .client import NotionAPIError, NotionClient
from .comments import CommentExtractor
from .databases import DatabaseExtractor
from .pages import AttachmentExtractor, PageExtractor
from .users import UserResolver

logger = logging.getLogger(__name__)

NOTION_NORMALIZER_VERSION = "0.1.0"


def _normalize_notion_id(value: str | None) -> str:
    """Canonical form of a Notion object id: dashes stripped, lowercased.

    Notion's REST API is inconsistent about whether ids come back dash-
    formatted (``2e79-7679-...``) or bare (``2e797679...``); the connection
    wizard persists the dash form. Normalising both sides before comparison
    makes the scope check robust. Non-id sentinels like ``"workspace"`` pass
    through unchanged (no dashes to strip) and simply never match a real id —
    which is the behaviour we want for workspace-parented docs.
    """
    return (value or "").replace("-", "").lower().strip()


def _filter_docs_by_scope(
    docs: list[DocRef], scope: set[str]
) -> tuple[list[DocRef], set[str]]:
    """Keep only DocRefs whose own id — or any ancestor's id — is in ``scope``.

    Transitive subtree semantics: sharing a page/database with a Notion
    integration shares its whole subtree, and the connection wizard only
    lists the "top-level" shared items, so a user who picks page A expects
    A and everything under it (sub-pages, database rows).

    Implementation: build ``{normalized source_id -> normalized parent_id}``
    from the *full* listed set, then for each doc walk up the parent chain.
    The check tests the current id against ``scope`` *before* consulting the
    parent map, so a scoped id that only ever appears as a *parent value*
    (e.g. a Notion "database" id, when only its child "data_source" objects
    are listed) is still honoured. Cycles / missing parents stop the walk.

    Each kept doc gets its matching scope id stamped onto its metadata as
    ``origin_scope_id`` so the manifest can later tell "out of scope" from
    "deleted at source" (Option B / scope-aware deletion).

    ``scope`` empty → return ``(docs, set())`` unchanged (backward compat,
    no origin tagging — there's no scope to attribute to).
    Returns ``(kept, matched_scope_ids)`` so the caller can log scoped ids
    that didn't resolve to anything without re-walking.
    """
    if not scope:
        return docs, set()

    parent_of: dict[str, str] = {}
    for d in docs:
        sid = _normalize_notion_id(d.source_id)
        if sid:
            parent_of[sid] = _normalize_notion_id((d.metadata or {}).get("parent_id"))

    matched: set[str] = set()

    def _matched_scope_id(doc: DocRef) -> str | None:
        """Return the (normalized) scope id this doc derives from, or None."""
        seen: set[str] = set()
        current = _normalize_notion_id(doc.source_id)
        while current and current not in seen:
            if current in scope:
                matched.add(current)
                return current
            seen.add(current)
            current = parent_of.get(current, "")
        return None

    kept: list[DocRef] = []
    for d in docs:
        origin = _matched_scope_id(d)
        if origin is None:
            continue
        # Stamp the origin onto the DocRef's metadata so the orchestrator can
        # forward it into manifest.upsert_document(origin_scope_id=...).
        if d.metadata is None:
            d.metadata = {}
        d.metadata["origin_scope_id"] = origin
        kept.append(d)
    return kept, matched


class NotionHarvesterPlugin(SourcePlugin):
    """Notion implementation of the SourcePlugin interface."""

    SOURCE_TYPE = "notion"

    def __init__(
        self,
        client: NotionClient,
        max_block_depth: int = 10,
        *,
        fetch_comments: bool = False,
        scope: list[str] | None = None,
    ):
        self.client = client
        self.pages = PageExtractor(client, max_depth=max_block_depth)
        self.databases = DatabaseExtractor(client)
        self.attachments = AttachmentExtractor(client)
        self.comments = CommentExtractor(client)
        self.users = UserResolver(client)
        self.fetch_comments = fetch_comments
        # Normalized set of Notion object ids the connection wizard selected
        # (``sources.notion.scope`` in mnemify.yaml). Empty → no
        # restriction (harvest everything the integration can see). Notion's
        # API is inconsistent about dashes in ids, so we compare canonical
        # (dash-stripped, lowercased) forms on both sides.
        self.scope: set[str] = {
            _normalize_notion_id(s) for s in (scope or []) if s
        }
        # Latch: flips to True after the first 401/403 from the comments
        # endpoint so we stop burning rate-limit budget on a permission
        # the integration doesn't have. Resets per plugin instance, i.e.
        # per harvest run.
        self._comments_disabled = False
        # Shared HTTP client for attachment downloads (Notion CDN is a
        # different host than the API, so we can't reuse client._http which
        # is pinned to api.notion.com via base_url). Lazily created on first
        # use so tests that never download attachments don't pay for it.
        self._attachment_http: httpx.AsyncClient | None = None

    # ── SourcePlugin interface ─────────────────────────────────────

    async def test_connection(self) -> HealthStatus:
        """Verify the Notion integration token works."""
        try:
            user = await self.client.test_connection()
            bot_name = user.get("name", "Unknown")
            return HealthStatus(
                healthy=True,
                source_type=self.SOURCE_TYPE,
                message=f"Connected as {bot_name}",
                details={"bot_id": user.get("id", ""), "bot_name": bot_name},
            )
        except Exception as e:
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=f"Connection failed: {e}",
            )

    async def list_documents(self, since: datetime | None = None) -> list[DocRef]:
        """List accessible Notion pages and databases as DocRefs.

        If ``self.scope`` is set, the result is narrowed to the selected
        objects and everything beneath them (see ``_filter_docs_by_scope``);
        otherwise everything the integration can see is returned.

        Pages are tagged document_type="page" (default).
        Databases are tagged document_type="database".

        DocRef.metadata includes:
            document_type -- "page" | "database"
            parent_type  -- "workspace" | "database_id" | "page_id"
            parent_id    -- database/page ID, or "workspace"
            created_at   -- ISO 8601 string
            properties   -- resolved flat property values (pages only)
            created_by   -- resolved display name of the page creator (pages only)
        """
        await self.users.load_users()

        # Pages
        pages = await self.pages.list_pages(since=since)
        page_refs = [
            DocRef(
                source_id=page.page_id,
                title=page.title,
                source_type=self.SOURCE_TYPE,
                source_url=page.url,
                modified_at=page.modified_at,
                metadata={
                    "document_type": "page",
                    "parent_type": page.parent_type,
                    "parent_id": page.parent_id,
                    "created_at": page.created_at.isoformat() if page.created_at else None,
                    "properties": self.databases.resolve_properties(page.properties),
                    "created_by": self.users.resolve_sync(page.created_by_id),
                    "created_by_id": page.created_by_id,
                    # Last editor — distinct from the creator when teammates
                    # edit the page after creation.
                    "last_modified_by": self.users.resolve_sync(page.last_edited_by_id),
                    "last_modified_by_id": page.last_edited_by_id,
                },
            )
            for page in pages
        ]

        # Databases (no since filter — databases don't have a last_edited_time
        # granular enough to be useful; always list them)
        db_list = await self.databases.list_databases()

        # Notion API ≥ 2025-09-03 split ``database`` into ``database``
        # (container) and ``data_source`` (the queryable schema + rows).
        # ``/search`` only returns data sources, so the wrapper database
        # is never harvested — and a page nested inside the data source
        # has a parent chain that goes
        #   page → data_source → (un-harvested database) → real ancestor.
        # Without the container's metadata, the breadcrumb walker can't
        # bridge that gap. Fetch each unique container once, in parallel,
        # and stash its title + own parent on the data source's DocRef.
        container_ids = sorted({
            db.parent_id for db in db_list
            if db.parent_type == "database_id"
            and db.parent_id
            and db.parent_id != "workspace"
        })
        containers_by_id: dict[str, dict] = {}
        if container_ids:
            results = await asyncio.gather(
                *(self._fetch_container_metadata(cid) for cid in container_ids),
                return_exceptions=False,
            )
            for cid, info in zip(container_ids, results):
                if info is not None:
                    containers_by_id[cid] = info

        db_refs = []
        for db in db_list:
            meta: dict = {
                "document_type": "database",
                "parent_type": db.parent_type,
                "parent_id": db.parent_id,
                "created_at": db.created_at.isoformat() if db.created_at else None,
                "property_count": len(db.properties_schema),
            }
            container = containers_by_id.get(db.parent_id)
            if container is not None:
                meta["container"] = container
            db_refs.append(
                DocRef(
                    source_id=db.database_id,
                    title=db.title,
                    source_type=self.SOURCE_TYPE,
                    source_url=db.url,
                    modified_at=db.modified_at,
                    metadata=meta,
                )
            )

        all_refs = page_refs + db_refs

        # Narrow to the wizard-selected pages/databases (and their subtrees).
        # `since` filtering already happened inside PageExtractor.list_pages
        # before these DocRefs were built; we filter on the assembled list.
        # (Caveat: on an incremental run a `since`-dropped intermediate page
        # won't be in the parent map, which can break a deep descendant's
        # ancestor link — acceptable, since databases are never `since`-
        # filtered and the user picks top-level items that rarely change.)
        if self.scope:
            before = len(all_refs)
            all_refs, matched = _filter_docs_by_scope(all_refs, self.scope)
            logger.info(
                "Notion scope: %d of %d listed docs match the configured "
                "scope (%d ids)",
                len(all_refs), before, len(self.scope),
            )
            missing = self.scope - matched
            if missing:
                logger.debug(
                    "Notion scope ids with no accessible docs: %s",
                    sorted(missing),
                )

        return all_refs

    async def _fetch_container_metadata(self, container_id: str) -> dict | None:
        """Resolve the un-listed database container that wraps a data source.

        Notion's ``/v1/databases/{id}`` endpoint still serves the legacy
        wrapper object: it returns the container's title and its own parent
        (the page or workspace that owns the database). We capture just
        enough — title + parent_type + parent_id — to let the breadcrumb
        walker bridge across the container and reach the harvested ancestor
        page above it. Failures (404, 401, transient) are logged and
        swallowed; callers handle ``None`` as "no bridge available".
        """
        try:
            raw = await self.client.get(f"/databases/{container_id}")
        except NotionAPIError as exc:
            logger.warning(
                "Couldn't fetch Notion database container %s for breadcrumb "
                "bridging: %s",
                container_id,
                exc,
            )
            return None
        cparent = raw.get("parent") or {}
        cparent_type = cparent.get("type", "")
        cparent_id = (
            cparent.get(cparent_type, "")
            if cparent_type != "workspace"
            else "workspace"
        )
        title_parts = raw.get("title") or []
        title = "".join(t.get("plain_text", "") for t in title_parts) or ""
        return {
            "id": container_id,
            "title": title,
            "parent_type": cparent_type,
            "parent_id": str(cparent_id),
        }

    async def fetch_document(self, doc_ref: DocRef) -> RawDocument:
        """Fetch a Notion page or database's full content in native JSON format.

        Dispatches on doc_ref.metadata["document_type"]:
          - "database" → fetch schema + rows via DatabaseExtractor
          - anything else (default "page") → fetch page + blocks + comments
        """
        if doc_ref.metadata.get("document_type") == "database":
            return await self._fetch_database_document(doc_ref)
        return await self._fetch_page_document(doc_ref)

    async def _fetch_page_document(self, doc_ref: DocRef) -> RawDocument:
        """Fetch a page's blocks and (optionally) comments.

        Markdown is rendered locally from the block tree by ``normalize()``
        — no second API call. The ``markdown`` envelope key is kept (set
        to ``None`` here) for backward-compatibility with any consumer
        that reads the raw JSON envelope on disk.

        Page-metadata + blocks and comments are fanned out concurrently;
        the global rate-limiter still bounds throughput, but parallel
        admission means the limiter is the only bottleneck instead of
        also serializing on Python-side awaits.

        ``asyncio.gather(..., return_exceptions=True)`` ensures both
        tasks are always awaited — even when ``get_full_page`` raises —
        so we never leak a background comments request that still
        counts against the 3 rps budget.
        """
        coros: list = [self.pages.get_full_page(doc_ref.source_id)]
        want_comments = self.fetch_comments and not self._comments_disabled
        if want_comments:
            coros.append(self.comments.get_page_comments(doc_ref.source_id))

        results = await asyncio.gather(*coros, return_exceptions=True)
        page_result = results[0]
        if isinstance(page_result, BaseException):
            # Page fetch failed — orchestrator's per-doc handler will log
            # and mark the document failed. Re-raise after the comments
            # task has already been awaited above so it can't leak.
            raise page_result
        page, blocks = page_result
        markdown: str | None = None

        if want_comments:
            comments_result = results[1]
            if isinstance(comments_result, NotionAPIError):
                if comments_result.status_code in (401, 403):
                    self._comments_disabled = True
                    logger.warning(
                        "Notion comments capability not granted (%s: %s); "
                        "disabling comment fetch for the rest of this run.",
                        comments_result.code,
                        comments_result.message,
                    )
                else:
                    logger.warning(
                        "Comments fetch failed for %s: %s",
                        doc_ref.source_id,
                        comments_result,
                    )
                comments = []
            elif isinstance(comments_result, BaseException):
                logger.warning(
                    "Comments fetch failed for %s: %s",
                    doc_ref.source_id,
                    comments_result,
                )
                comments = []
            else:
                comments = comments_result
        else:
            # Comments off — saves one rate-limited Notion call per page.
            comments = []

        native = {
            "page": {
                "page_id": page.page_id,
                "title": page.title,
                "url": page.url,
                "created_at": page.created_at.isoformat() if page.created_at else None,
                "modified_at": page.modified_at.isoformat() if page.modified_at else None,
                "parent_type": page.parent_type,
                "parent_id": page.parent_id,
            },
            "blocks": self.pages.blocks_to_native_json(blocks),
            "markdown": markdown,
            "comments": self.comments.comments_to_dicts(comments),
        }
        content = json.dumps(native, ensure_ascii=False).encode("utf-8")

        found = self.attachments.find_attachments(blocks, parent_page_id=doc_ref.source_id)
        att_refs = [
            AttachmentRef(
                source_id=att.block_id,
                filename=att.filename,
                url=att.url,
                mime_type=att.mime_type,
            )
            for att in found
        ]

        return RawDocument(
            source_id=doc_ref.source_id,
            title=page.title,
            content=content,
            format="json",
            metadata={
                "document_type": "page",
                "url": page.url,
                "block_count": self.pages._count_blocks(blocks),
                "attachment_count": len(att_refs),
            },
            attachments=att_refs,
        )

    async def _fetch_database_document(self, doc_ref: DocRef) -> RawDocument:
        """Fetch a database's schema and all rows."""
        db, rows = await asyncio.gather(
            self.databases.get_database(doc_ref.source_id),
            self.databases.query_database(doc_ref.source_id),
        )

        native = {
            "database": self.databases.database_to_dict(db),
            "rows": self.databases.rows_to_dicts(rows),
        }
        content = json.dumps(native, ensure_ascii=False).encode("utf-8")

        return RawDocument(
            source_id=doc_ref.source_id,
            title=db.title,
            content=content,
            format="json",
            metadata={
                "document_type": "database",
                "url": db.url,
                "row_count": len(rows),
                "property_count": len(db.properties_schema),
            },
            # Databases have no attachments
        )

    async def fetch_attachment(self, att_ref: AttachmentRef) -> bytes:
        """Download a single attachment by URL using a shared HTTP client."""
        if self._attachment_http is None:
            self._attachment_http = httpx.AsyncClient(timeout=60.0)
        response = await self._attachment_http.get(att_ref.url)
        response.raise_for_status()
        return response.content

    async def aclose(self) -> None:
        """Close plugin-owned resources (shared attachment HTTP client)."""
        if self._attachment_http is not None:
            await self._attachment_http.aclose()
            self._attachment_http = None

    async def mark_harvested(
        self,
        source_id: str,
        timestamp: str,
        property_name: str = "Harvested At",
    ) -> None:
        """Write back a harvest timestamp to a Notion page property.

        Uses PATCH /pages/{id} to set a date property.
        Silently swallows 409 Conflict (race with concurrent edits) and
        404 Not Found (page deleted between harvest and write-back).
        All other errors propagate so the orchestrator can log and continue.
        """
        from .client import NotionAPIError

        payload = {
            "properties": {
                property_name: {
                    "date": {
                        "start": timestamp,
                    }
                }
            }
        }
        try:
            await self.client.patch(f"/pages/{source_id}", json=payload)
        except NotionAPIError as e:
            if e.status_code in (404, 409):
                logger.debug(
                    f"mark_harvested: ignoring {e.status_code} for {source_id!r}"
                )
                return
            raise

    def normalize(self, raw: RawDocument) -> NormalizedDocument:
        """Convert a Notion raw JSON envelope into a clean markdown sidecar.

        Output is pure text — no YAML frontmatter. All structured metadata
        (url, parent_type, properties, etc.) lives in the manifest. The raw
        JSON on disk is unchanged, so the block tree remains recoverable
        for any future consumer that wants it.

        Page envelope → render markdown from blocks via
        :meth:`PageExtractor.blocks_to_markdown`, then append comments
        (rendered as a markdown ``--- Comments ---`` section).

        Database envelope → schema-and-titles summary.

        The legacy ``markdown`` envelope key (Notion's pre-rendered
        markdown) is honored when present so historical raw files keep
        producing the same output, but new harvests no longer set it
        (Layer 2a removed the per-page ``/markdown`` API call).
        """
        envelope = json.loads(raw.content)

        if "database" in envelope:
            body = self._database_to_markdown(envelope)
        else:
            cached_md = envelope.get("markdown")
            if cached_md:
                body = cached_md
            else:
                blocks = PageExtractor.blocks_from_json(envelope.get("blocks") or [])
                body = self.pages.blocks_to_markdown(blocks)
            comments_text = self._comments_to_markdown(envelope.get("comments") or [])
            if comments_text:
                body = f"{body.rstrip()}\n{comments_text}"

        return NormalizedDocument(
            source_id=raw.source_id,
            title=raw.title,
            markdown=f"{body.rstrip()}\n" if body.strip() else "",
            frontmatter={},
            normalizer_version=NOTION_NORMALIZER_VERSION,
        )

    @staticmethod
    def _comments_to_markdown(comment_dicts: list[dict]) -> str:
        """Render comments as a small markdown section under the page body."""
        if not comment_dicts:
            return ""
        lines = ["", "---", "", "## Comments", ""]
        for c in comment_dicts:
            author = c.get("created_by") or "Unknown"
            text = (c.get("text") or "").strip()
            if not text:
                continue
            lines.append(f"- **{author}**: {text}")
        return "\n".join(lines) if len(lines) > 5 else ""

    _DB_MARKDOWN_MAX_ROWS = 50
    _DB_MARKDOWN_MAX_PROP_COLS = 4

    @staticmethod
    def _format_db_cell(value) -> str:
        """Coerce a resolved property value into a markdown-table-safe cell.

        Pipe characters are escaped (otherwise they break pipe-table syntax)
        and embedded newlines are flattened. Lists join with ", "; None and
        empty values render as empty strings.
        """
        if value is None:
            return ""
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if v not in (None, ""))
        elif isinstance(value, bool):
            value = "Yes" if value else "No"
        else:
            value = str(value)
        return value.replace("|", "\\|").replace("\n", " ").strip()

    @classmethod
    def _database_to_markdown(cls, native: dict) -> str:
        """Render a database envelope as a markdown table of its rows.

        Notion databases don't map cleanly to a single markdown artifact,
        but the most useful representation is a row × property table —
        each row's title plus a few key properties, capped at
        ``_DB_MARKDOWN_MAX_ROWS`` rows and ``_DB_MARKDOWN_MAX_PROP_COLS``
        non-title property columns to keep the artifact readable. Any
        remaining rows are signalled with a ``…and N more`` footer so
        the reader knows the database is truncated.
        """
        db = native.get("database", {})
        title = db.get("title", "Untitled Database")
        schema = db.get("properties_schema", {}) or {}
        rows = native.get("rows", []) or []

        lines = [f"# {title}", ""]

        if not rows:
            if schema:
                lines.append("**Properties:** " + ", ".join(schema.keys()))
            return "\n".join(lines).rstrip()

        # Identify the title column so we don't render it twice (we always
        # surface row.title in the first column). Schema entries are dicts
        # like {"type": "title", "name": "..."}; missing "type" keeps the
        # legacy test-fixture shape working.
        title_prop = next(
            (n for n, s in schema.items() if isinstance(s, dict) and s.get("type") == "title"),
            None,
        )
        prop_cols = [n for n in schema.keys() if n != title_prop][
            : cls._DB_MARKDOWN_MAX_PROP_COLS
        ]

        # First column is the row's title. Use the schema's actual title-prop
        # name (e.g. "Name", "Task", "Question") when we found one, so users
        # see the column header they configured in Notion. Otherwise label it
        # generically as "Title".
        headers = [title_prop or "Title"] + prop_cols
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")

        visible = rows[: cls._DB_MARKDOWN_MAX_ROWS]
        for row in visible:
            row_title = cls._format_db_cell(row.get("title") or "Untitled")
            props = row.get("properties") or {}
            cells = [row_title] + [cls._format_db_cell(props.get(c)) for c in prop_cols]
            lines.append("| " + " | ".join(cells) + " |")

        if len(rows) > cls._DB_MARKDOWN_MAX_ROWS:
            lines.append("")
            lines.append(f"_…and {len(rows) - cls._DB_MARKDOWN_MAX_ROWS} more rows._")

        return "\n".join(lines)

