"""Slack source plugin — implements :class:`SourcePlugin` for the orchestrator.

Two emission modes share one channel walk:

- ``thread`` mode emits one document per thread (parent + replies),
  with ``source_id = slack:{channel}:thread:{thread_ts}``.
- ``channel_summary`` mode emits one document per active channel-day,
  with ``source_id = slack:{channel}:summary:{YYYY-MM-DD}``.
- ``both`` produces both, distinct source_ids — no collision.

Per-channel ``mode`` and ``past_days`` overrides in
``ChannelSpec`` win over the source-level defaults.

Mentions in message bodies (``<@U0123>``, ``<#C0123|name>``) are
resolved during ``fetch_document`` (where async is available) and
the resolved-name dict is stored in ``RawDocument.metadata`` so the
sync ``normalize`` method can substitute without re-entering async.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from src.harvester import (
    AttachmentRef,
    DocRef,
    HealthStatus,
    NormalizedDocument,
    RawDocument,
    SourcePlugin,
)
from .client import SlackAPIError, SlackAuthError, SlackClient
from .fields import flatten_summary_fields, flatten_thread_fields
from .models import SlackConfig
from .names import NameCache
from .normalizer import slack_summary_to_markdown, slack_thread_to_markdown
from .threads import MessageExtractor, _effective_modified_ts, _ts_to_datetime

logger = logging.getLogger(__name__)

_MENTION_ID_RE = re.compile(r"<([@#])([UCDG][A-Z0-9]+)(?:\|[^>]*)?>")


class SlackHarvesterPlugin(SourcePlugin):
    """Slack implementation of the :class:`SourcePlugin` interface."""

    SOURCE_TYPE = "slack"

    def __init__(self, config: SlackConfig, *, client: SlackClient | None = None) -> None:
        self.config = config
        self._client = client or SlackClient(token="")  # tests inject a fake; factory injects real
        self._extractor = MessageExtractor(self._client)
        self._names = NameCache(self._client, ttl_seconds=config.name_cache_ttl_seconds)
        # Lazy caches populated on first use.
        self._team_domain: str | None = None
        self._channel_info_cache: dict[str, dict] = {}

    # ── SourcePlugin interface ────────────────────────────────────

    async def test_connection(self) -> HealthStatus:
        try:
            auth = await self._client.auth_test()
        except SlackAuthError as exc:
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=f"Slack auth failed: {exc.slack_error or exc}. "
                        f"Check {self.config.token_env} in .env (User OAuth Token, xoxp-…).",
            )
        except SlackAPIError as exc:
            return HealthStatus(
                healthy=False,
                source_type=self.SOURCE_TYPE,
                message=f"Slack API unreachable: {exc}",
            )

        team = auth.get("team", "?")
        user = auth.get("user", "?")
        # Best-effort warmup; failure is non-fatal (cache fills on demand).
        try:
            await self._names.warmup_workspace_users()
        except SlackAPIError as exc:
            logger.warning("name cache warmup skipped: %s", exc)

        return HealthStatus(
            healthy=True,
            source_type=self.SOURCE_TYPE,
            message=f"Slack OK: authenticated as {user} in workspace {team}",
            details={"team": team, "user": user, "channel_count": len(self.config.channels)},
        )

    async def list_documents(self, since: datetime | None = None) -> list[DocRef]:
        # FIXME(scope-aware-since): the orchestrator passes ``since=None`` to
        # avoid the scope-expansion bug source-wide ``since`` caused on
        # Notion/Confluence. Slack uses ``since`` server-side via
        # ``oldest=ts`` on conversations.history, so disabling it widens the
        # window to ``past_days`` only. When this plugin is wired into the UI,
        # restore the optimization with a scope-aware comparison against
        # ``config.channels`` recorded in the manifest.
        results: list[DocRef] = []
        for spec in self.config.channels:
            try:
                channel_info = await self._get_channel_info(spec.id)
            except SlackAPIError as exc:
                logger.warning("slack: skipping channel %s — %s", spec.id, exc)
                continue
            mode = spec.mode or self.config.document_mode_default
            past_days = spec.past_days or self.config.past_days
            effective_since = self._effective_since(since, past_days)
            oldest = effective_since.timestamp()

            if mode in ("thread", "both"):
                async for root in self._extractor.list_thread_starters(spec.id, oldest=oldest):
                    results.append(self._thread_doc_ref(channel_info, root))

            if mode in ("channel_summary", "both"):
                try:
                    days = await self._extractor.list_active_days(spec.id, oldest=oldest)
                except SlackAPIError as exc:
                    logger.warning("slack: list_active_days failed for %s — %s", spec.id, exc)
                    days = []
                for day in days:
                    results.append(self._summary_doc_ref(channel_info, day))

        logger.debug("SlackHarvesterPlugin.list_documents: %d docs across %d channels",
                     len(results), len(self.config.channels))
        return results

    async def fetch_document(self, doc_ref: DocRef) -> RawDocument:
        kind, channel_id, identifier = self._parse_source_id(doc_ref.source_id)
        if kind == "thread":
            return await self._fetch_thread(doc_ref, channel_id, identifier)
        if kind == "summary":
            return await self._fetch_summary(doc_ref, channel_id, identifier)
        raise ValueError(f"unknown slack source_id kind: {doc_ref.source_id!r}")

    async def fetch_attachment(self, att_ref: AttachmentRef) -> bytes:
        return await self._client.download_file(att_ref.url)

    def normalize(self, raw: RawDocument) -> NormalizedDocument:
        doc_type = raw.metadata.get("document_type")
        if doc_type == "thread":
            md = slack_thread_to_markdown(raw.content, raw.metadata)
        elif doc_type == "channel_summary":
            md = slack_summary_to_markdown(raw.content, raw.metadata)
        else:
            md = raw.content.decode("utf-8", errors="replace")
        return NormalizedDocument(
            source_id=raw.source_id,
            title=raw.title,
            markdown=md,
            frontmatter={},
            normalizer_version="0.1.0",
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ── DocRef builders ───────────────────────────────────────────

    def _thread_doc_ref(self, channel_info: dict, root: dict) -> DocRef:
        thread_ts = root.get("ts", "")
        modified_ts = _effective_modified_ts(root)
        modified_at = _ts_to_datetime(modified_ts)
        channel_name = channel_info.get("name") or channel_info.get("id", "")
        author_id = root.get("user") or root.get("username") or "?"
        text_lines = (root.get("text") or "").strip().splitlines()
        preview = text_lines[0][:80] if text_lines else "(no text)"
        title = f"#{channel_name}: {preview}".rstrip(": ")
        return DocRef(
            source_id=f"slack:{channel_info.get('id')}:thread:{thread_ts}",
            title=title,
            source_type=self.SOURCE_TYPE,
            source_url=None,  # permalink computed at fetch time
            modified_at=modified_at,
            metadata={
                "document_type": "thread",
                "channel_id": channel_info.get("id"),
                "channel_name": channel_name,
                "thread_ts": thread_ts,
                "root_author_id": author_id,
                "modified_ts": modified_ts,
            },
        )

    def _summary_doc_ref(self, channel_info: dict, day) -> DocRef:
        day_iso = day.isoformat()
        channel_name = channel_info.get("name") or channel_info.get("id", "")
        # Summary "modified at" is end-of-day so a daily-cron incremental
        # picks it up the next morning. Content-hash gating in the
        # orchestrator suppresses re-writes when the content didn't change.
        modified_at = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
        return DocRef(
            source_id=f"slack:{channel_info.get('id')}:summary:{day_iso}",
            title=f"#{channel_name} — {day_iso}",
            source_type=self.SOURCE_TYPE,
            source_url=None,
            modified_at=modified_at,
            metadata={
                "document_type": "channel_summary",
                "channel_id": channel_info.get("id"),
                "channel_name": channel_name,
                "summary_day": day_iso,
            },
        )

    # ── Fetch implementations ─────────────────────────────────────

    async def _fetch_thread(self, doc_ref: DocRef, channel_id: str, thread_ts: str) -> RawDocument:
        channel_info = await self._get_channel_info(channel_id)
        messages = await self._extractor.get_thread(channel_id, thread_ts)
        await self._preresolve_mentions(messages)
        permalink = self._build_permalink(channel_id, thread_ts)
        envelope = {"channel": channel_info, "messages": messages}
        attachments = self._extract_attachments(doc_ref.source_id, messages)
        metadata = flatten_thread_fields(
            channel=channel_info,
            root=messages[0] if messages else {},
            replies=messages,
            name_snapshot=self._names.snapshot(),
            permalink=permalink,
        )
        metadata["resolved_mentions"] = self._names.snapshot()
        return RawDocument(
            source_id=doc_ref.source_id,
            title=doc_ref.title,
            content=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
            format="json",
            metadata=metadata,
            attachments=attachments,
        )

    async def _fetch_summary(self, doc_ref: DocRef, channel_id: str, day_iso: str) -> RawDocument:
        channel_info = await self._get_channel_info(channel_id)
        try:
            day = datetime.fromisoformat(day_iso).date()
        except ValueError as exc:
            raise ValueError(f"invalid summary day in source_id: {day_iso!r}") from exc
        messages = await self._extractor.list_messages_in_day(channel_id, day)
        await self._preresolve_mentions(messages)
        envelope = {"channel": channel_info, "day": day_iso, "messages": messages}
        # references list = thread roots present in the day window
        references = sorted({
            f"slack:{channel_id}:thread:{m.get('thread_ts') or m.get('ts')}"
            for m in messages
            if m.get("ts")
        })
        attachments = self._extract_attachments(doc_ref.source_id, messages)
        metadata = flatten_summary_fields(
            channel=channel_info,
            day_iso=day_iso,
            messages=messages,
            references=references,
            name_snapshot=self._names.snapshot(),
        )
        metadata["resolved_mentions"] = self._names.snapshot()
        return RawDocument(
            source_id=doc_ref.source_id,
            title=doc_ref.title,
            content=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
            format="json",
            metadata=metadata,
            attachments=attachments,
        )

    # ── Helpers ───────────────────────────────────────────────────

    async def _get_channel_info(self, channel_id: str) -> dict:
        if channel_id in self._channel_info_cache:
            return self._channel_info_cache[channel_id]
        info = await self._client.conversations_info(channel_id)
        self._channel_info_cache[channel_id] = info
        return info

    async def _preresolve_mentions(self, messages: list[dict]) -> None:
        """Scan all message texts for ``<@U…>`` / ``<#C…>`` and warm the cache.

        After this, :meth:`NameCache.snapshot` returns a dict the sync
        normalizer can substitute against without re-entering async.
        """
        ids: set[tuple[str, str]] = set()  # (kind '@'|'#', id)
        for msg in messages:
            text = msg.get("text") or ""
            for m in _MENTION_ID_RE.finditer(text):
                ids.add((m.group(1), m.group(2)))
        for kind, ident in ids:
            try:
                if kind == "@":
                    await self._names.user_display(ident)
                else:
                    await self._names.channel_display(ident)
            except SlackAPIError as exc:
                logger.warning("preresolve %s%s failed: %s — leaving raw ID", kind, ident, exc)

    def _extract_attachments(self, source_id: str, messages: list[dict]) -> list[AttachmentRef]:
        out: list[AttachmentRef] = []
        for msg in messages:
            for f in msg.get("files", []) or []:
                if not f or f.get("mode") == "tombstone":
                    continue
                url = f.get("url_private") or f.get("url_private_download")
                if not url:
                    continue
                out.append(AttachmentRef(
                    source_id=source_id,
                    filename=f.get("name") or f.get("title") or f.get("id", "file"),
                    url=url,
                    mime_type=f.get("mimetype"),
                    size=f.get("size"),
                ))
        return out

    def _build_permalink(self, channel_id: str, thread_ts: str) -> str | None:
        """Construct ``https://{team}.slack.com/archives/{channel}/p{ts_no_dot}``.

        Returns ``None`` when the team domain isn't yet known and a
        single ``team.info`` call would be the only blocker — better
        to omit than to drown logs in domain lookups. The plugin warms
        the domain on first thread fetch.
        """
        if not self._team_domain:
            return None
        # Slack permalink expects ts without the dot, prefixed with "p".
        # E.g. ts "1700000000.123456" → p1700000000123456.
        ts_compact = thread_ts.replace(".", "")
        return f"https://{self._team_domain}.slack.com/archives/{channel_id}/p{ts_compact}"

    @staticmethod
    def _parse_source_id(source_id: str) -> tuple[str, str, str]:
        # slack:{channel_id}:{kind}:{identifier}
        parts = source_id.split(":", 3)
        if len(parts) != 4 or parts[0] != "slack":
            raise ValueError(f"malformed slack source_id: {source_id!r}")
        return parts[2], parts[1], parts[3]  # (kind, channel_id, identifier)

    @staticmethod
    def _effective_since(since: datetime | None, past_days: int) -> datetime:
        floor = datetime.now(tz=timezone.utc) - timedelta(days=past_days)
        if since is None:
            return floor
        # Use the *later* of the two so we never widen beyond past_days
        # but always honour the manifest-driven incremental cutoff.
        return max(since, floor)
