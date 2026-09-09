"""Jira source plugin — implements :class:`SourcePlugin` for the harvester.

Implemented in ATL-24 (with ATL-41 lazy story-points cache bundled in).

Per-method implementation tasks (from the Phase 1 Atlassian plan, §4):

- ``test_connection``    → ATL-24 (calls ``/rest/api/3/myself``)
- ``list_documents``     → ATL-24 (delegates to :class:`IssueExtractor`;
  populates the lazy story-points field cache on first call — ATL-41)
- ``fetch_document``     → ATL-24 (assembles :class:`RawDocument`
  ``format="json"`` with the raw issue JSON — ADF preserved — per §3.2)
- ``fetch_attachment``   → ATL-31 (downloads via :class:`JiraClient`) —
  delegates to :meth:`JiraClient.download_attachment` which uses the
  authenticated ``requests.Session`` that ``atlassian-python-api`` sets
  up (basic auth via email + API token).  Attachment refs are populated
  by :meth:`fetch_document` from ``fields.attachment[]``.
``mark_harvested`` is a deliberate no-op in Phase 1 (see decisions doc
entry 2026-04-19 — no write-back to Jira).  ``aclose`` delegates to
:meth:`JiraClient.aclose` so any authenticated session the underlying
``atlassian-python-api`` opened is released cleanly.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from src.harvester import (
    AttachmentRef,
    DocRef,
    HealthStatus,
    NormalizedDocument,
    RawDocument,
    SourcePlugin,
)
from .client import JiraAuthError, JiraClient
from .fields import discover_story_points_field, flatten_issue_fields
from .issues import IssueExtractor
from .models import JiraConfig

logger = logging.getLogger(__name__)


def _parse_iso_utc(value: str | None) -> datetime | None:
    """Parse an Atlassian-emitted ISO-8601 timestamp into a naive-UTC datetime.

    Atlassian serialises ``updated`` / ``created`` as
    ``"2026-04-15T09:21:33.123+0000"`` — Python's ``fromisoformat`` on
    older runtimes chokes on the compact ``+0000`` offset.  Normalise it
    to ``+00:00`` before parsing, convert to UTC, and drop the tzinfo so
    :class:`DocRef.modified_at` is uniform with the other plugins.
    """
    if not value:
        return None
    try:
        # ``fromisoformat`` on 3.11+ accepts ``+0000``, but on earlier
        # versions (and for belt-and-braces safety) expand to ``+00:00``.
        normalised = value
        if len(normalised) >= 5 and normalised[-5] in ("+", "-") and normalised[-3] != ":":
            normalised = normalised[:-2] + ":" + normalised[-2:]
        dt = datetime.fromisoformat(normalised)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        from datetime import timezone
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class JiraHarvesterPlugin(SourcePlugin):
    """Jira implementation of the :class:`SourcePlugin` interface."""

    SOURCE_TYPE = "jira"

    def __init__(
        self,
        config: JiraConfig,
        *,
        client: JiraClient | None = None,
    ) -> None:
        self.config = config
        # The factory in ``__init__.py`` (ATL-25) resolves the email/token
        # env vars and injects a pre-configured :class:`JiraClient` here.
        # Tests (and smoke construction) that do not need the network may
        # omit ``client`` — we then construct a credential-less stub that
        # will fail on any network call but permits contract assertions.
        if client is None:
            client = JiraClient(
                base_url=config.base_url,
                email="",
                token="",
            )
        self.client = client
        self.issues = IssueExtractor(self.client)
        # ATL-41 — lazy cache for the story-points custom-field id.
        # Pre-populated from YAML override when present; else ``None``
        # until :meth:`list_documents` auto-discovers.  The separate
        # ``_discovered`` flag is load-bearing: ``None`` is a valid
        # *result* (site has no story-points field) and without the flag
        # we would re-hit ``/rest/api/3/field`` on every invocation.
        self._story_points_field: str | None = config.story_points_field
        self._story_points_discovered: bool = config.story_points_field is not None

    # ── SourcePlugin interface ─────────────────────────────────────

    async def test_connection(self) -> HealthStatus:
        """Probe ``/rest/api/3/myself`` to verify credentials + connectivity."""
        try:
            user = await self.client.get_myself()
        except JiraAuthError as exc:
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=(
                    f"Jira authentication failed ({exc.status_code}): check "
                    f"{self.config.email_env!r} and {self.config.token_env!r}"
                ),
            )
        except Exception as exc:  # noqa: BLE001 — probe must not raise
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=f"Connection failed: {exc}",
            )

        display = user.get("displayName") or user.get("emailAddress") or "Unknown"
        return HealthStatus(
            healthy=True,
            source_type=self.SOURCE_TYPE,
            message=f"Connected as {display}",
            details={
                "account_id": user.get("accountId", ""),
                "display_name": display,
            },
        )

    async def list_documents(self, since: datetime | None = None) -> list[DocRef]:
        """List every issue across ``config.project_keys`` as :class:`DocRef` objects.

        FIXME(scope-aware-since): the orchestrator currently passes
        ``since=None`` so newly-scoped projects don't get filtered out by an
        outdated watermark (the bug that source-wide ``since`` caused on
        Notion/Confluence). Jira uses ``since`` *server-side* via JQL
        ``updated >= …``, so disabling it here trades correctness for cost.
        When this plugin is wired into the UI, restore the optimization by
        comparing the current ``project_keys`` against the per-run scope
        recorded in the manifest and passing ``since`` only when scope is
        unchanged. Until then the plugin will re-list the full project on
        every run; the orchestrator's per-doc Layer 1 still skips unchanged
        issues so we only pay listing cost, not refetch cost.

        Populates ``DocRef.metadata`` with the §3.2 subset available from
        the JQL list response (``summary``, ``status``, ``project_key``,
        ``updated``, ``issue_type``) — enough for filter decisions
        without a second fetch.

        Story-points field auto-discovery (ATL-41):
          First call triggers :func:`discover_story_points_field` unless
          a YAML override (``sources.jira.story_points_field``) has
          already pre-populated the cache.  Subsequent calls use the
          memoised id — ``/rest/api/3/field`` is hit at most once per
          plugin instance.
        """
        # ATL-41 — one-shot discovery on first invocation, unless the
        # YAML override short-circuited us in ``__init__``.
        if not self._story_points_discovered:
            try:
                self._story_points_field = await discover_story_points_field(self.client)
            except Exception as exc:  # noqa: BLE001 — tolerate restricted field-listing
                logger.warning(
                    "Jira story-points field auto-discovery failed (%s); "
                    "story points will be emitted as None",
                    exc,
                )
                self._story_points_field = None
            self._story_points_discovered = True

        if not self.config.project_keys:
            return []

        doc_refs: list[DocRef] = []
        async for issue in self.issues.list_issues(
            self.config.project_keys,
            since=since,
        ):
            fields = issue.get("fields") or {}
            project_obj = fields.get("project") or {}
            issue_type_obj = fields.get("issuetype") or {}
            status_obj = fields.get("status") or {}

            issue_key = issue.get("key", "")
            summary = fields.get("summary") or issue_key

            project_key = project_obj.get("key")
            if not project_key and "-" in issue_key:
                project_key = issue_key.rsplit("-", 1)[0]

            updated_raw = fields.get("updated")
            modified_at = _parse_iso_utc(updated_raw)

            doc_refs.append(
                DocRef(
                    source_id=issue_key,
                    title=summary,
                    source_type=self.SOURCE_TYPE,
                    source_url=None,  # Full browse URL lives on RawDocument.metadata
                    modified_at=modified_at,
                    metadata={
                        "document_type": "issue",
                        "summary": summary,
                        "status": status_obj.get("name"),
                        "project_key": project_key,
                        "updated": updated_raw,
                        "issue_type": issue_type_obj.get("name"),
                    },
                )
            )
        return doc_refs

    async def fetch_document(self, doc_ref: DocRef) -> RawDocument:
        """Fetch an issue's full content as :class:`RawDocument` (format='json').

        ``RawDocument.content`` is the raw ``/rest/api/3/issue/{key}`` JSON
        encoded as UTF-8 bytes — stored as-is, ADF preserved, no flattening
        (decision 2026-04-19).  ``RawDocument.metadata`` is produced by
        :func:`flatten_issue_fields` using the cached story-points field id.
        """
        issue = await self.issues.get_full_issue(doc_ref.source_id)
        content = json.dumps(issue, ensure_ascii=False).encode("utf-8")

        metadata = flatten_issue_fields(issue, self._story_points_field)

        # ATL-24: populate AttachmentRef list from fields.attachment[]; the
        # actual download body is ATL-31 but refs travel with the document
        # so the orchestrator has everything it needs when that lands.
        fields = issue.get("fields") or {}
        raw_attachments = fields.get("attachment") or []
        attachments: list[AttachmentRef] = []
        for att in raw_attachments:
            att_url = att.get("content")
            filename = att.get("filename")
            if not att_url or not filename:
                continue
            size = att.get("size")
            if not isinstance(size, int):
                size = None
            attachments.append(
                AttachmentRef(
                    source_id=doc_ref.source_id,
                    filename=filename,
                    url=att_url,
                    mime_type=att.get("mimeType"),
                    size=size,
                )
            )

        title = fields.get("summary") or doc_ref.title or doc_ref.source_id

        return RawDocument(
            source_id=doc_ref.source_id,
            title=title,
            content=content,
            format="json",
            metadata=metadata,
            attachments=attachments,
        )

    async def fetch_attachment(self, att_ref: AttachmentRef) -> bytes:
        """Download an issue attachment via the authenticated client.

        Delegates to :meth:`JiraClient.download_attachment`, which reuses
        the authenticated ``requests.Session`` set up by
        ``atlassian-python-api`` (basic auth: email + API token) and is
        already ``to_thread``-wrapped and tenacity-retried on 429/5xx.

        The orchestrator owns where the bytes land on disk (see plan
        §3.3 and ``src/harvester/orchestrator.py:307-352``) — the plugin
        only returns raw bytes and never touches the filesystem.
        """
        return await self.client.download_attachment(att_ref.url)

    def normalize(self, raw: RawDocument) -> NormalizedDocument:
        """Convert the stored issue JSON to clean Markdown with YAML frontmatter."""
        import json as _json

        from .normalizer import _build_frontmatter, jira_to_markdown
        issue = _json.loads(raw.content)
        fields = issue.get("fields") or {}
        fm = _build_frontmatter(issue, fields, raw.metadata, base_url=self.config.base_url)
        markdown = jira_to_markdown(raw.content, raw.metadata, base_url=self.config.base_url)

        return NormalizedDocument(
            source_id=raw.source_id,
            title=raw.title,
            markdown=markdown,
            frontmatter=fm,
            normalizer_version="0.1.0",
        )

    async def aclose(self) -> None:
        """Release the underlying :class:`JiraClient` session (best-effort)."""
        await self.client.aclose()

    # ``mark_harvested`` intentionally inherits :class:`SourcePlugin`'s
    # no-op default — Phase 1 does not write back to Jira (2026-04-19
    # decisions doc entry).
