"""Flatten Slack raw envelopes into manifest-shaped metadata dicts.

Pure functions, no I/O. The plugin calls these at fetch-time to build
the ``RawDocument.metadata`` dict that gets merged into the manifest's
``documents.metadata`` JSON column.

Field set per envelope:

- ``flatten_thread_fields`` — one thread (root + replies) → metadata
  with ``document_type="thread"``, channel info, participants list,
  reply count, reaction summary, permalink, ``is_dm`` flag.
- ``flatten_summary_fields`` — one channel-day → metadata with
  ``document_type="channel_summary"``, channel info, day, message
  count, list of source_ids of the threads it spans.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

# ── Helpers ───────────────────────────────────────────────────────


def _ts_iso(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _is_dm(channel: dict) -> bool:
    if channel.get("is_im") or channel.get("is_mpim"):
        return True
    cid = channel.get("id", "") or ""
    return cid.startswith("D") or cid.startswith("MPDM") or cid.startswith("G")


def _channel_name(channel: dict) -> str:
    if channel.get("is_im"):
        return "(direct message)"
    if channel.get("is_mpim"):
        return "(group dm)"
    name = channel.get("name") or channel.get("name_normalized") or channel.get("id", "")
    if channel.get("is_archived"):
        return f"[archived] #{name}"
    return f"#{name}"


def _author_name(msg: dict, name_snapshot: dict[str, str]) -> str:
    """Best-effort author display string.

    Bot messages don't carry ``user`` — fall back to ``username`` or
    ``bot_profile.name`` so the rendered message isn't anonymous.
    """
    user_id = msg.get("user")
    if user_id:
        return name_snapshot.get(user_id, f"@{user_id}")
    if msg.get("subtype") == "bot_message":
        return msg.get("username") or (msg.get("bot_profile") or {}).get("name") or "@bot"
    return msg.get("username") or "@unknown"


def _participants(messages: list[dict], name_snapshot: dict[str, str]) -> list[dict[str, str]]:
    seen_ids: list[str] = []
    seen_set: set[str] = set()
    for m in messages:
        uid = m.get("user")
        if not uid or uid in seen_set:
            continue
        seen_set.add(uid)
        seen_ids.append(uid)
    return [{"id": uid, "name": name_snapshot.get(uid, f"@{uid}")} for uid in seen_ids]


def _reaction_summary(messages: list[dict]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for m in messages:
        for r in m.get("reactions", []) or []:
            name = r.get("name")
            count = int(r.get("count", 0) or 0)
            if name and count:
                counts[name] += count
    return dict(counts)


def _attachment_count(messages: list[dict]) -> int:
    n = 0
    for m in messages:
        for f in m.get("files", []) or []:
            if f and f.get("mode") != "tombstone":
                n += 1
    return n


def _text_preview(text: str | None, *, limit: int = 80) -> str:
    if not text:
        return ""
    text = text.strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ── Public flatteners ─────────────────────────────────────────────


def flatten_thread_fields(
    *,
    channel: dict,
    root: dict,
    replies: list[dict],
    name_snapshot: dict[str, str],
    permalink: str | None = None,
) -> dict[str, Any]:
    """Build a metadata dict for a single thread.

    ``replies`` includes the root message at index 0 (Slack's own
    ``conversations.replies`` convention). ``permalink`` is optional —
    callers may pre-compute it from ``team_info()`` and the root ts.
    """
    root_text = root.get("text", "") or ""
    # Reaction-only messages: render the reaction set as a preview so
    # the title isn't blank.
    if not root_text and root.get("reactions"):
        emoji_bits = [f":{r['name']}:" for r in root["reactions"] if r.get("name")]
        root_text = " ".join(emoji_bits)

    return {
        "document_type": "thread",
        "channel_id": channel.get("id"),
        "channel_name": _channel_name(channel),
        "is_dm": _is_dm(channel),
        "is_archived": bool(channel.get("is_archived")),
        "thread_ts": root.get("ts"),
        "root_author_id": root.get("user"),
        "root_author_name": _author_name(root, name_snapshot),
        "root_text_preview": _text_preview(root_text),
        "reply_count": max(0, len(replies) - 1),  # exclude the root itself
        "participant_count": len({m.get("user") for m in replies if m.get("user")}),
        "participants": _participants(replies, name_snapshot),
        "created_at": _ts_iso(root.get("ts")),
        "last_reply_at": _ts_iso(replies[-1].get("ts")) if replies else None,
        "permalink": permalink,
        "reaction_summary": _reaction_summary(replies),
        "attachment_count": _attachment_count(replies),
        "pinned": bool(root.get("pinned_to")),
    }


def flatten_summary_fields(
    *,
    channel: dict,
    day_iso: str,
    messages: list[dict],
    references: list[str],
    name_snapshot: dict[str, str],
) -> dict[str, Any]:
    """Build a metadata dict for a channel-day summary.

    ``references`` is the list of ``slack:{channel}:thread:{ts}``
    source_ids that this summary covers — useful for the knowledge-map
    edge mining step downstream (summary → threads it indexes).
    """
    return {
        "document_type": "channel_summary",
        "channel_id": channel.get("id"),
        "channel_name": _channel_name(channel),
        "is_dm": _is_dm(channel),
        "is_archived": bool(channel.get("is_archived")),
        "summary_day": day_iso,
        "message_count": len(messages),
        "participant_count": len({m.get("user") for m in messages if m.get("user")}),
        "participants": _participants(messages, name_snapshot),
        "references": list(references),
        "reaction_summary": _reaction_summary(messages),
        "attachment_count": _attachment_count(messages),
    }
