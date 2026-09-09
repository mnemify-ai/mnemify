"""Slack message JSON → pure-body markdown.

Two entry points dispatch on ``metadata["document_type"]``:

- :func:`slack_thread_to_markdown` — root + replies, sectioned per
  message with author + timestamp headings.
- :func:`slack_summary_to_markdown` — channel-day digest, bulleted
  one-line excerpts grouped by hour.

Both are sync functions: the plugin pre-resolves all user/channel
mentions during ``fetch_document`` (where async is available) and
stores the resolved-name dict in ``metadata["resolved_mentions"]``.
This module just substitutes from that dict — no async, no I/O.

Pure-body output: no YAML frontmatter, no metadata headers — the
.md file is directly usable as LLM input. All structured metadata
lives in the manifest's ``documents.metadata`` JSON column.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

# Slack mrkdwn placeholders.
# <@U0123>                       → user mention
# <@U0123|alice>                 → user mention with cached name (rare)
# <#C0123|general>               → channel link
# <#C0123>                       → channel link without name
# <!here> / <!channel> / <!everyone>
# <https://example.com|label>    → linked url
# <https://example.com>          → bare url
# &amp; / &lt; / &gt;            → escaped specials
_MENTION_RE = re.compile(r"<([@#!])([^|>]+)(?:\|([^>]+))?>")
_LINK_RE = re.compile(r"<((?:https?|mailto):[^|>]+)(?:\|([^>]+))?>")


def _ts_to_short(ts: str | None) -> str:
    """Format a Slack ts as ``2026-05-13 14:22 UTC`` (drop seconds)."""
    if not ts:
        return ""
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return ""
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _ts_to_hhmm(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%H:%M")
    except (TypeError, ValueError):
        return ""


def _unescape_specials(text: str) -> str:
    """Slack escapes ``&``, ``<``, ``>`` in message text. Reverse it."""
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _resolve_mentions(text: str, name_snapshot: dict[str, str]) -> str:
    """Substitute ``<@U…>`` / ``<#C…>`` / ``<!cmd>`` with display strings."""

    def _sub_mention(m: re.Match[str]) -> str:
        kind, identifier, label = m.group(1), m.group(2), m.group(3)
        if kind == "@":
            return name_snapshot.get(identifier, label and f"@{label}" or f"@{identifier}")
        if kind == "#":
            # Slack always sends the channel name in <#C…|name> when
            # known; fall back to cache only if absent.
            if label:
                return f"#{label}"
            return name_snapshot.get(identifier, f"#{identifier}")
        if kind == "!":
            # <!here>, <!channel>, <!everyone>, or <!subteam^S0123|name>
            if "^" in identifier:
                return f"@{label}" if label else f"@{identifier.split('^', 1)[0]}"
            return f"@{identifier}"
        return m.group(0)

    text = _MENTION_RE.sub(_sub_mention, text)
    text = _LINK_RE.sub(
        lambda m: f"[{m.group(2) or m.group(1)}]({m.group(1)})",
        text,
    )
    return _unescape_specials(text)


def _render_reactions(reactions: list[dict] | None) -> str:
    if not reactions:
        return ""
    bits = [f":{r['name']}: ×{int(r.get('count', 0) or 0)}" for r in reactions if r.get("name")]
    return " · ".join(bits)


def _render_files(files: list[dict] | None) -> str:
    if not files:
        return ""
    lines: list[str] = []
    for f in files:
        if not f or f.get("mode") == "tombstone":
            lines.append("📎 [file removed]")
            continue
        name = f.get("name") or f.get("title") or f.get("id", "file")
        fid = f.get("id", "")
        lines.append(f"📎 [{name}](attachment://{fid})" if fid else f"📎 {name}")
    return "\n".join(lines)


def _author_label(msg: dict, name_snapshot: dict[str, str]) -> str:
    user_id = msg.get("user")
    if user_id:
        return name_snapshot.get(user_id, f"@{user_id}")
    if msg.get("subtype") == "bot_message":
        return msg.get("username") or (msg.get("bot_profile") or {}).get("name") or "@bot"
    return msg.get("username") or "@unknown"


def _message_body(msg: dict, name_snapshot: dict[str, str]) -> str:
    """Render a single message's body — text + reactions + files."""
    text = msg.get("text", "") or ""
    body_text = _resolve_mentions(text, name_snapshot).strip() if text else ""
    reactions_line = _render_reactions(msg.get("reactions"))
    files_block = _render_files(msg.get("files"))

    parts: list[str] = []
    if body_text:
        parts.append(body_text)
    elif reactions_line:
        # Reaction-only message — promote reactions into the body so
        # the section isn't empty under its heading.
        parts.append(reactions_line)
        reactions_line = ""  # don't repeat below
    if reactions_line:
        parts.append(f"_{reactions_line}_")
    if files_block:
        parts.append(files_block)
    return "\n\n".join(parts) if parts else "_(empty message)_"


# ── Public entry points ───────────────────────────────────────────


def slack_thread_to_markdown(raw_content: bytes, metadata: dict[str, Any]) -> str:
    """Render a thread envelope to markdown.

    ``raw_content`` is the JSON-encoded ``{"channel": …, "messages": [root, …replies]}``
    written by the plugin. ``metadata`` carries the resolved-name
    snapshot at ``["resolved_mentions"]`` plus channel/permalink info.
    """
    envelope = json.loads(raw_content.decode("utf-8"))
    messages: list[dict] = envelope.get("messages", []) or []
    name_snapshot: dict[str, str] = metadata.get("resolved_mentions") or {}
    channel_name = metadata.get("channel_name") or "(channel)"
    permalink = metadata.get("permalink")

    if not messages:
        return f"# {channel_name} — empty thread\n"

    root = messages[0]
    root_text = root.get("text") or ""
    title_preview = (
        _resolve_mentions(root_text, name_snapshot).strip().split("\n")[0][:80]
        if root_text
        else _render_reactions(root.get("reactions")) or "(reaction-only thread)"
    )
    root_author = _author_label(root, name_snapshot)
    title = f"# {root_author} in {channel_name}: {title_preview}".rstrip(":")

    lines: list[str] = [title, ""]
    if permalink:
        lines.append(f"[Open in Slack]({permalink})")
        lines.append("")

    for msg in messages:
        author = _author_label(msg, name_snapshot)
        when = _ts_to_short(msg.get("ts"))
        lines.append(f"## {when} — {author}")
        lines.append("")
        lines.append(_message_body(msg, name_snapshot))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def slack_summary_to_markdown(raw_content: bytes, metadata: dict[str, Any]) -> str:
    """Render a channel-day summary envelope to markdown.

    ``raw_content`` is JSON-encoded ``{"channel": …, "day": "YYYY-MM-DD",
    "messages": […]}``. Output is bulleted one-line excerpts in
    chronological order, grouped by thread root when discoverable.
    """
    envelope = json.loads(raw_content.decode("utf-8"))
    messages: list[dict] = envelope.get("messages", []) or []
    name_snapshot: dict[str, str] = metadata.get("resolved_mentions") or {}
    day = envelope.get("day") or metadata.get("summary_day") or ""
    channel_name = metadata.get("channel_name") or "(channel)"
    n_msgs = len(messages)
    n_people = metadata.get("participant_count") or len(
        {m.get("user") for m in messages if m.get("user")}
    )

    header = f"# {channel_name} — {day} ({n_msgs} message{'s' if n_msgs != 1 else ''}, {n_people} {'person' if n_people == 1 else 'people'})"
    lines: list[str] = [header, ""]

    # Group by thread_ts (or own ts when standalone) so threaded replies
    # appear under their parent. Preserve chronological order of the parents.
    grouped: dict[str, list[dict]] = {}
    parent_order: list[str] = []
    for msg in messages:
        parent_key = msg.get("thread_ts") or msg.get("ts") or ""
        if parent_key not in grouped:
            grouped[parent_key] = []
            parent_order.append(parent_key)
        grouped[parent_key].append(msg)

    for parent_ts in parent_order:
        group = grouped[parent_ts]
        # Make sure the parent (if present) is first; replies sorted by ts.
        group.sort(key=lambda m: float(m.get("ts", "0") or "0"))
        parent_msg = group[0]
        excerpt = (parent_msg.get("text") or "").strip().replace("\n", " ")
        excerpt = _resolve_mentions(excerpt, name_snapshot)
        if not excerpt:
            excerpt = _render_reactions(parent_msg.get("reactions")) or "(no text)"
        if len(excerpt) > 140:
            excerpt = excerpt[:139] + "…"
        author = _author_label(parent_msg, name_snapshot)
        when = _ts_to_hhmm(parent_msg.get("ts"))
        lines.append(f"- **{when} {author}**: {excerpt}")
        # Reply bullets indented under the parent.
        for reply in group[1:]:
            r_excerpt = (reply.get("text") or "").strip().replace("\n", " ")
            r_excerpt = _resolve_mentions(r_excerpt, name_snapshot)
            if not r_excerpt:
                r_excerpt = _render_reactions(reply.get("reactions")) or "(no text)"
            if len(r_excerpt) > 120:
                r_excerpt = r_excerpt[:119] + "…"
            r_author = _author_label(reply, name_snapshot)
            r_when = _ts_to_hhmm(reply.get("ts"))
            lines.append(f"  - **{r_when} {r_author}**: {r_excerpt}")

    return "\n".join(lines).rstrip() + "\n"
