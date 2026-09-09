"""Jira JSON envelope → clean Markdown with YAML frontmatter.

:func:`jira_to_markdown` is the single entry point.  It parses the raw
``/rest/api/3/issue/{key}`` JSON stored by the harvester, converts the ADF
description and comment bodies to Markdown via :func:`markdown_from_adf`,
and wraps the result in a YAML frontmatter block so the compiler extractor
receives structured, human-readable content instead of raw JSON.
"""

from __future__ import annotations

import json
import re

import yaml

from .adf import markdown_from_adf


def jira_to_markdown(
    raw_content: bytes,
    metadata: dict,
    *,
    base_url: str | None = None,
) -> str:
    """Convert a raw Jira issue JSON payload to Markdown with YAML frontmatter.

    Parameters
    ----------
    raw_content:
        UTF-8-encoded bytes of the full ``/rest/api/3/issue/{key}`` response.
    metadata:
        Metadata dict already attached to the :class:`RawDocument` — typically
        the output of :func:`flatten_issue_fields`.  May be a minimal dict
        containing only ``key``/``project_key`` (e.g. in the smoke-test path).
        Values here take precedence over what is derived from the JSON.
    base_url:
        Jira site base URL (e.g. ``https://acme.atlassian.net``).  When given,
        the ``url`` frontmatter field is set to ``{base_url}/browse/{key}``.
    """
    issue = json.loads(raw_content)
    fields = issue.get("fields") or {}

    fm = _build_frontmatter(issue, fields, metadata, base_url=base_url)
    frontmatter_block = _render_yaml_frontmatter(fm)

    key = fm.get("key") or ""
    summary = fm.get("summary") or ""
    heading = f"# {key} — {summary}" if (key and summary) else f"# {key or summary}"

    body_parts: list[str] = [heading, ""]

    # Description
    body_parts.append("## Description")
    desc_adf = fields.get("description")
    if desc_adf:
        desc_md = markdown_from_adf(desc_adf)
        body_parts.append(desc_md if desc_md.strip() else "(no description)")
    else:
        body_parts.append("(no description)")

    # Comments — only if present, ordered by created ascending.
    comment_data = fields.get("comment")
    comments: list[dict] = []
    if isinstance(comment_data, dict):
        comments = comment_data.get("comments") or []
    elif isinstance(comment_data, list):
        comments = comment_data

    if comments:
        comments_sorted = sorted(comments, key=lambda c: c.get("created") or "")
        body_parts.append("")
        body_parts.append("## Comments")
        for comment in comments_sorted:
            ts = comment.get("created") or ""
            author = (comment.get("author") or {}).get("displayName") or "Unknown"
            body_parts.append(f"### {ts} — {author}")
            comment_body = comment.get("body")
            if comment_body:
                comment_md = markdown_from_adf(comment_body)
                if comment_md.strip():
                    body_parts.append(comment_md)

    body = "\n".join(body_parts)
    body = re.sub(r"\n{3,}", "\n\n", body)

    return f"{frontmatter_block}\n{body}\n"


def _build_frontmatter(
    issue: dict,
    fields: dict,
    metadata: dict,
    *,
    base_url: str | None,
) -> dict:
    """Build the ordered frontmatter dict from issue JSON + metadata."""
    fm: dict = {}

    fm["source"] = "jira"

    key = metadata.get("key") or issue.get("key") or ""
    source_id = metadata.get("source_id") or key
    if source_id:
        fm["source_id"] = source_id
    if key:
        fm["key"] = key

    issue_type = (
        metadata.get("issue_type")
        or (fields.get("issuetype") or {}).get("name")
    )
    if issue_type:
        fm["issue_type"] = issue_type

    status = (
        metadata.get("status")
        or (fields.get("status") or {}).get("name")
    )
    if status:
        fm["status"] = status

    # flatten_issue_fields uses "assignee_name"; spec wants "assignee"
    assignee = (
        metadata.get("assignee_name")
        or metadata.get("assignee")
        or (fields.get("assignee") or {}).get("displayName")
    )
    if assignee:
        fm["assignee"] = assignee

    reporter = (
        metadata.get("reporter_name")
        or metadata.get("reporter")
        or (fields.get("reporter") or {}).get("displayName")
    )
    if reporter:
        fm["reporter"] = reporter

    labels = metadata.get("labels") or fields.get("labels") or []
    if labels:
        fm["labels"] = list(labels)

    project_key = (
        metadata.get("project_key")
        or (fields.get("project") or {}).get("key")
    )
    if project_key:
        fm["project_key"] = project_key

    created = metadata.get("created") or fields.get("created")
    if created:
        fm["created"] = created

    updated = metadata.get("updated") or fields.get("updated")
    if updated:
        fm["updated"] = updated

    story_points = metadata.get("story_points")
    if story_points is not None:
        fm["story_points"] = story_points

    parent_key = (fields.get("parent") or {}).get("key")
    if parent_key:
        fm["parent_key"] = parent_key

    summary = fields.get("summary") or metadata.get("summary") or ""
    if summary:
        fm["summary"] = summary

    if base_url and key:
        fm["url"] = f"{base_url}/browse/{key}"
    elif metadata.get("url"):
        fm["url"] = metadata["url"]

    return fm


def _render_yaml_frontmatter(fm: dict) -> str:
    """Serialize *fm* to a YAML frontmatter block (``---\\n...\\n---``)."""
    body = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return f"---\n{body}---"
