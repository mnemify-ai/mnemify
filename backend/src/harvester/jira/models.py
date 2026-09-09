"""Jira plugin data models.

Scaffolded in ATL-03.  The :class:`JiraConfig` dataclass is the
Phase-1-final schema the YAML ``sources.jira`` block parses into — no
fields are expected to be added before ATL-25.  :class:`JiraIssue` is
the in-memory representation used by :class:`IssueExtractor` (ATL-23)
and is shaped but otherwise unused by the ATL-03 scaffold.

Separate auth env vars (``JIRA_EMAIL`` + ``JIRA_API_TOKEN``) are the
default, per the 2026-04-19 decisions doc entry; users who share a
single Atlassian token across Confluence + Jira can point both sources'
``token_env`` at the same variable.

``story_points_field`` is ``None`` by default, which triggers auto-
discovery via ``/rest/api/3/field`` (ATL-40).  Users whose Jira site
renames the custom field or whose API access is restricted can set an
explicit ``customfield_XXXXX`` id via the YAML config as an escape hatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class JiraConfig:
    """Configuration for the Jira harvester.

    Matches the ``sources.jira`` block of ``mnemify.yaml`` 1:1 (see
    ``src/config_file.py`` docstring for the example).

    Attributes:
        base_url:           Jira site base URL (e.g.
                            ``https://your-org.atlassian.net``).  Do *not*
                            include a ``/wiki`` suffix — that is
                            Confluence-specific.
        email_env:          Name of the env var that holds the Atlassian
                            account email (defaults to ``JIRA_EMAIL``).
        token_env:          Name of the env var that holds the Atlassian
                            API token (defaults to ``JIRA_API_TOKEN``).
        project_keys:       List of Jira project keys to harvest via JQL
                            (e.g. ``["CONN", "OPS"]``).  Phase 1 has no
                            "harvest everything" mode — enumeration is
                            JQL-based, not board-based.
        concurrency:        Per-source concurrency override; defaults to
                            3 (the Phase 1 locked-in default).
        story_points_field: Optional explicit override for the custom
                            field id (e.g. ``"customfield_10026"``).
                            When ``None`` (default), the plugin auto-
                            discovers it via ``/rest/api/3/field``
                            (ATL-40 / ATL-41).  Never hardcode
                            ``customfield_10016`` — that is a
                            historical default that does not hold for
                            every Jira Cloud site.
    """

    base_url: str
    email_env: str = "JIRA_EMAIL"
    token_env: str = "JIRA_API_TOKEN"
    project_keys: list[str] = field(default_factory=list)
    concurrency: int = 3
    story_points_field: str | None = None


@dataclass
class JiraIssue:
    """Normalised representation of a single Jira issue.

    Populated by :class:`IssueExtractor.get_full_issue` (ATL-23) from
    the raw ``/rest/api/3/issue/{key}`` response.  The ``raw_json``
    payload is the authoritative content that the plugin persists
    byte-for-byte via :class:`RawDocument` (``format="json"``) — ADF
    bodies are preserved verbatim, never flattened in storage (decision
    2026-04-19).

    ATL-03 only declares the shape; field population lives in ATL-23.
    """

    issue_key: str                       # e.g. "CONN-123"
    summary: str
    project_key: str
    issue_type: str                      # "Story", "Bug", "Epic", ...
    status: str
    priority: str | None = None
    assignee_id: str | None = None
    assignee_name: str | None = None
    reporter_id: str | None = None
    reporter_name: str | None = None
    created: datetime | None = None
    updated: datetime | None = None
    labels: list[str] = field(default_factory=list)
    story_points: float | None = None
    resolved_story_points_field: str | None = None  # which customfield id was used
    url: str = ""
    attachment_count: int = 0
    raw_json: dict = field(default_factory=dict)    # raw REST payload, ADF preserved
