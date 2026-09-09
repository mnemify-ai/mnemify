"""User / channel name resolution with TTL caching.

Slack messages carry placeholders like ``<@U0123>`` (user mention) and
``<#C0123|name>`` (channel link). Rendering them as ``@alice`` /
``#general`` requires a name lookup. ``users.info`` and
``conversations.info`` are individually cheap but a busy thread can
mention dozens of users — without a cache we'd spam the API per harvest.

Design choices:

- In-process LRU + TTL. Single-user CLI; persistence buys nothing.
- Keyed on ``(team_id, user_id)`` so Slack Connect cross-team mentions
  resolve correctly. ``team_id=None`` means the calling token's own team.
- Tombstones (deleted users / unknown channels) are cached for 24h —
  longer than positive entries — so we don't re-hit the API on every
  re-fetch of an old thread that mentions someone who left the company.
- On API failure during resolution the cache returns the raw ID as a
  degraded display string. The harvest must not abort just because a
  name lookup glitched; the manifest already has the canonical IDs.

The cache is meant to be **drained synchronously by the normalizer**:
the plugin pre-resolves all mentions during ``fetch_document`` (where
async is available) and stores the resolved-name dict in
``RawDocument.metadata["resolved_mentions"]`` so the sync ``normalize``
method can do dict lookups without re-entering async land.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from .client import SlackAPIError, SlackClient

logger = logging.getLogger(__name__)

_TOMBSTONE_TTL_SECONDS = 24 * 60 * 60


@dataclass
class _CacheEntry:
    display: str
    expires_at: float


class NameCache:
    """TTL'd in-process cache for user and channel display names.

    Thread-safety is asyncio-coroutine-safe (single event loop) — the
    per-key locks guarantee at-most-one in-flight refresh per key, so
    a burst of concurrent normalizations doesn't fan out into a stampede
    of ``users.info`` calls for the same user.
    """

    def __init__(self, client: SlackClient, *, ttl_seconds: int = 3600) -> None:
        self._client = client
        self._ttl = ttl_seconds
        # (team_id_or_None, user_id) → entry
        self._users: dict[tuple[str | None, str], _CacheEntry] = {}
        # channel_id → entry
        self._channels: dict[str, _CacheEntry] = {}
        # per-key locks so concurrent misses for the same key share one fetch
        self._user_locks: dict[tuple[str | None, str], asyncio.Lock] = {}
        self._channel_locks: dict[str, asyncio.Lock] = {}

    # ── Public lookups ────────────────────────────────────────────

    async def user_display(self, user_id: str, *, team_id: str | None = None) -> str:
        """Return ``@alice`` (or ``[deleted user]`` / raw ID on failure)."""
        key = (team_id, user_id)
        now = time.time()
        cached = self._users.get(key)
        if cached and cached.expires_at > now:
            return cached.display

        lock = self._user_locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Re-check after acquiring the lock — another waiter may have filled it.
            cached = self._users.get(key)
            if cached and cached.expires_at > time.time():
                return cached.display
            display = await self._fetch_user(user_id, team_id=team_id)
            self._users[key] = _CacheEntry(
                display=display,
                expires_at=time.time() + (
                    _TOMBSTONE_TTL_SECONDS if display.startswith("[") else self._ttl
                ),
            )
            return display

    async def channel_display(self, channel_id: str) -> str:
        """Return ``#general`` (or ``[unknown #channel]`` / raw ID on failure)."""
        now = time.time()
        cached = self._channels.get(channel_id)
        if cached and cached.expires_at > now:
            return cached.display

        lock = self._channel_locks.setdefault(channel_id, asyncio.Lock())
        async with lock:
            cached = self._channels.get(channel_id)
            if cached and cached.expires_at > time.time():
                return cached.display
            display = await self._fetch_channel(channel_id)
            self._channels[channel_id] = _CacheEntry(
                display=display,
                expires_at=time.time() + (
                    _TOMBSTONE_TTL_SECONDS if display.startswith("[") else self._ttl
                ),
            )
            return display

    # ── Bulk warmup ────────────────────────────────────────────────

    async def warmup_workspace_users(self) -> None:
        """One-shot ``users.list`` paginated load. Cheap-ish for a workspace
        under ~10k members; for larger workspaces, set
        ``name_cache_ttl_seconds`` low and rely on per-user lookups instead.
        """
        cursor: str | None = None
        loaded = 0
        while True:
            try:
                page = await self._client.users_list(cursor=cursor, limit=200)
            except SlackAPIError as exc:
                logger.warning("name cache warmup failed: %s", exc)
                return
            for member in page.get("members", []) or []:
                uid = member.get("id")
                if not uid:
                    continue
                display = self._format_user(member)
                # team_id key is None — warmup applies to the calling token's team.
                self._users[(None, uid)] = _CacheEntry(
                    display=display,
                    expires_at=time.time() + self._ttl,
                )
                loaded += 1
            cursor = (page.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                break
        logger.debug("name cache warmup loaded %d users", loaded)

    # ── Snapshot for the normalizer ────────────────────────────────

    def snapshot(self) -> dict[str, str]:
        """Export a flat ``{id: display}`` dict for the sync normalizer.

        Both user IDs and channel IDs share the namespace — the IDs
        themselves are unambiguous (``U…`` vs ``C…``/``D…``/``G…``).
        """
        out: dict[str, str] = {}
        for (_team, uid), entry in self._users.items():
            out[uid] = entry.display
        for cid, entry in self._channels.items():
            out[cid] = entry.display
        return out

    # ── Internals ──────────────────────────────────────────────────

    async def _fetch_user(self, user_id: str, *, team_id: str | None) -> str:
        try:
            user = await self._client.users_info(user_id, team_id=team_id)
        except SlackAPIError as exc:
            code = getattr(exc, "slack_error", "") or ""
            if code in ("user_not_found", "user_not_visible"):
                return "[deleted user]"
            logger.warning("users.info(%s) failed: %s — using raw ID", user_id, exc)
            return f"@{user_id}"
        return self._format_user(user)

    async def _fetch_channel(self, channel_id: str) -> str:
        try:
            ch = await self._client.conversations_info(channel_id)
        except SlackAPIError as exc:
            code = getattr(exc, "slack_error", "") or ""
            if code in ("channel_not_found", "missing_scope"):
                return "[unknown #channel]"
            logger.warning("conversations.info(%s) failed: %s — using raw ID", channel_id, exc)
            return f"#{channel_id}"
        return self._format_channel(ch)

    @staticmethod
    def _format_user(user: dict) -> str:
        if user.get("deleted"):
            return "[deleted user]"
        profile = user.get("profile") or {}
        # Prefer the display_name, then real_name, then the user's @-name.
        name = (
            profile.get("display_name_normalized")
            or profile.get("display_name")
            or profile.get("real_name_normalized")
            or profile.get("real_name")
            or user.get("name")
            or user.get("id", "")
        )
        return f"@{name}" if name else f"@{user.get('id', '')}"

    @staticmethod
    def _format_channel(channel: dict) -> str:
        if channel.get("is_im"):
            return "(direct message)"
        if channel.get("is_mpim"):
            return "(group dm)"
        name = channel.get("name") or channel.get("name_normalized") or channel.get("id", "")
        prefix = "#" if not channel.get("is_private") else "🔒#"
        return f"{prefix}{name}"
