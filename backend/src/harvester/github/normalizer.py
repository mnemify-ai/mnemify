"""GitHub raw envelopes → pure-body markdown.

GitHub bodies are already GFM markdown so this module is mostly
templating + comment-thread assembly. No HTML conversion. Mirrors
the style (but not the parser complexity) of the Confluence
normalizer.

Dispatches on ``metadata["document_type"]``:

- ``issue``      → title + body + ``## Comments``
- ``pr``         → title + body + ``## Reviews`` + ``## Comments``
- ``discussion`` → title + body + ``## Comments`` (with replies indented)
- ``readme``     → ``# {repo} — README`` + base64-decoded body

Comments authored by minimized accounts (or with ``isMinimized`` set
on discussion comments) are skipped — they're typically off-topic
or moderated and would noise up the LLM context.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from src.harvester import report_extraction_warning

# ── Helpers ───────────────────────────────────────────────────────


def _author(login: str | None) -> str:
    return f"@{login}" if login else "@ghost"


def _date_short(value: str | None) -> str:
    """Return ``2026-05-13 14:22 UTC`` or ``""`` from an ISO 8601 string."""
    if not value:
        return ""
    # GitHub uses both ``Z`` and ``+00:00`` — normalize.
    return value.replace("T", " ").replace("Z", " UTC")[:23]


def _decode_readme_content(readme: dict) -> str:
    encoding = readme.get("encoding") or "base64"
    raw = readme.get("content") or ""
    if encoding == "base64":
        try:
            return base64.b64decode(raw).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — fall back to raw on any decode glitch
            return raw
    return raw


def _render_labels(labels: list[str] | None) -> str:
    if not labels:
        return ""
    return ", ".join(f"`{name}`" for name in labels)


def _render_comments(comments: list[dict], *, body_key: str = "body", author_path: str = "user.login") -> str:
    """Build a ``## Comments`` block from REST or GraphQL comment dicts."""
    if not comments:
        return ""
    lines: list[str] = ["", "## Comments", ""]
    for c in comments:
        author = _resolve_author(c, author_path)
        when = _date_short(c.get("created_at") or c.get("createdAt"))
        body = (c.get(body_key) or "").strip()
        if not body:
            continue
        lines.append(f"### {author} — {when}".rstrip(" —"))
        lines.append("")
        lines.append(body)
        lines.append("")
    return "\n".join(lines).rstrip()


def _resolve_author(d: dict, path: str) -> str:
    """Walk a dotted path like ``user.login`` or ``author.login``."""
    cur: Any = d
    for key in path.split("."):
        if not isinstance(cur, dict):
            return "@ghost"
        cur = cur.get(key)
    return _author(cur)


# ── Per-document_type renderers ───────────────────────────────────


def _issue_to_markdown(envelope: dict, metadata: dict) -> str:
    issue = envelope.get("issue") or {}
    comments = envelope.get("comments") or []
    title = issue.get("title") or "(untitled)"
    state = issue.get("state") or "?"
    author = _author(_login(issue.get("user")))
    labels = _render_labels(metadata.get("labels"))

    header_bits = [f"**State:** {state}", f"**Author:** {author}"]
    if labels:
        header_bits.append(f"**Labels:** {labels}")

    lines: list[str] = [
        f"# [Issue #{issue.get('number', '?')}] {title}",
        "",
        " · ".join(header_bits),
        "",
        (issue.get("body") or "").strip() or "_(no body)_",
    ]
    comments_block = _render_comments(comments, body_key="body", author_path="user.login")
    if comments_block:
        lines.append("")
        lines.append(comments_block)
    return "\n".join(lines).rstrip() + "\n"


def _pr_to_markdown(envelope: dict, metadata: dict) -> str:
    pr = envelope.get("pr") or {}
    comments = envelope.get("comments") or []
    reviews = envelope.get("reviews") or []
    title = pr.get("title") or "(untitled)"
    author = _author(_login(pr.get("user")))
    labels = _render_labels(metadata.get("labels"))

    state_chip = "merged" if pr.get("merged") else (pr.get("state") or "?")
    if pr.get("draft"):
        state_chip = f"{state_chip} · draft"

    header_bits = [f"**State:** {state_chip}", f"**Author:** {author}"]
    head, base = pr.get("head") or {}, pr.get("base") or {}
    if head.get("ref") and base.get("ref"):
        header_bits.append(f"**Branch:** `{head['ref']}` → `{base['ref']}`")
    if labels:
        header_bits.append(f"**Labels:** {labels}")

    lines: list[str] = [
        f"# [PR #{pr.get('number', '?')}] {title}",
        "",
        " · ".join(header_bits),
        "",
        (pr.get("body") or "").strip() or "_(no body)_",
    ]

    reviews_block = _render_pr_reviews(reviews)
    if reviews_block:
        lines.append("")
        lines.append(reviews_block)

    comments_block = _render_comments(comments, body_key="body", author_path="user.login")
    if comments_block:
        lines.append("")
        lines.append(comments_block)
    return "\n".join(lines).rstrip() + "\n"


def _render_pr_reviews(reviews: list[dict]) -> str:
    if not reviews:
        return ""
    lines: list[str] = ["", "## Reviews", ""]
    for r in reviews:
        state = (r.get("state") or "?").replace("_", " ").title()
        author = _author(_login(r.get("user")))
        when = _date_short(r.get("submitted_at"))
        body = (r.get("body") or "").strip()
        header = f"### {author} — {state}" + (f" — {when}" if when else "")
        lines.append(header)
        lines.append("")
        lines.append(body if body else "_(no review body — verdict only)_")
        lines.append("")
    return "\n".join(lines).rstrip()


def _discussion_to_markdown(envelope: dict, metadata: dict) -> str:
    discussion = envelope.get("discussion") or {}
    comments = discussion.get("comments") or []
    title = discussion.get("title") or "(untitled)"
    author = _author(_login_v2(discussion.get("author")))
    category = (discussion.get("category") or {}).get("name") or "?"
    answered = "answered" if (discussion.get("answer") or {}).get("id") else "unanswered"

    lines: list[str] = [
        f"# [Discussion #{discussion.get('number', '?')}] {title}",
        "",
        f"**Category:** {category} · **Author:** {author} · **{answered}**",
        "",
        (discussion.get("body") or "").strip() or "_(no body)_",
    ]

    visible = [c for c in comments if not c.get("isMinimized")]
    for _c in comments:
        if _c.get("isMinimized"):
            report_extraction_warning("github_minimized_comment", "")
    if visible:
        lines.append("")
        lines.append("## Comments")
        lines.append("")
        for c in visible:
            c_author = _author(_login_v2(c.get("author")))
            when = _date_short(c.get("createdAt"))
            body = (c.get("body") or "").strip()
            if not body:
                continue
            lines.append(f"### {c_author} — {when}".rstrip(" —"))
            lines.append("")
            lines.append(body)
            lines.append("")
            for reply in c.get("replies", {}).get("nodes", []) or []:
                if reply.get("isMinimized"):
                    report_extraction_warning("github_minimized_comment", "")
                    continue
                r_author = _author(_login_v2(reply.get("author")))
                r_when = _date_short(reply.get("createdAt"))
                r_body = (reply.get("body") or "").strip()
                if not r_body:
                    continue
                lines.append(f"  - **{r_author}** — {r_when}: {r_body.replace(chr(10), ' ')[:300]}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _readme_to_markdown(envelope: dict, metadata: dict) -> str:
    readme = envelope.get("readme") or {}
    repo = metadata.get("repo") or "(repo)"
    body = _decode_readme_content(readme).strip() or "_(empty README)_"
    return f"# {repo} — README\n\n{body}\n"


# ── Tiny author helpers ───────────────────────────────────────────


def _login(user: dict | None) -> str | None:
    return (user or {}).get("login")


def _login_v2(author: dict | None) -> str | None:
    """GraphQL author objects: ``{login: "..."}`` (no nested ``user``)."""
    return (author or {}).get("login")


# ── Public entry point ───────────────────────────────────────────


def github_to_markdown(raw_content: bytes, metadata: dict[str, Any]) -> str:
    """Dispatch on ``metadata['document_type']`` to the right renderer."""
    envelope = json.loads(raw_content.decode("utf-8"))
    doc_type = metadata.get("document_type")
    if doc_type == "issue":
        return _issue_to_markdown(envelope, metadata)
    if doc_type == "pr":
        return _pr_to_markdown(envelope, metadata)
    if doc_type == "discussion":
        return _discussion_to_markdown(envelope, metadata)
    if doc_type == "readme":
        return _readme_to_markdown(envelope, metadata)
    return raw_content.decode("utf-8", errors="replace")
