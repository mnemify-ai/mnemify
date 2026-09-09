"""Confluence plugin data models.

Scaffolded in ATL-02.  The :class:`ConfluenceConfig` dataclass is the
Phase-1-final schema the YAML ``sources.confluence`` block parses into —
no fields are expected to be added before ATL-14.  :class:`ConfluencePage`
is the in-memory representation used by :class:`PageExtractor` (ATL-11)
and is shaped but otherwise unused by the ATL-02 scaffold.

Separate auth env vars (`CONFLUENCE_EMAIL` + `CONFLUENCE_API_TOKEN`) are
the default, per the 2026-04-19 decisions doc entry; users who share a
single Atlassian token across Confluence + Jira can point both sources'
``token_env`` at the same variable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ConfluenceConfig:
    """Configuration for the Confluence harvester.

    Matches the ``sources.confluence`` block of ``mnemify.yaml`` 1:1
    (see ``src/config_file.py`` docstring for the example).

    Attributes:
        base_url:        Confluence site base URL (e.g.
                         ``https://your-org.atlassian.net/wiki``).  Must
                         include the ``/wiki`` suffix for Cloud.
        email_env:       Name of the env var that holds the Atlassian
                         account email (defaults to ``CONFLUENCE_EMAIL``).
        token_env:       Name of the env var that holds the Atlassian API
                         token (defaults to ``CONFLUENCE_API_TOKEN``).
        space_keys:      List of space keys to harvest (required; no
                         "harvest everything" mode in Phase 1).  Space
                         *keys* only — never space names.
        page_ids:        List of page ids to harvest as subtrees (each
                         id pulls the page itself plus every descendant
                         page).  Lets Manage Scope narrow a harvest to a
                         branch of a space instead of the whole space.
        include_archived:Whether to include archived pages in the list.
                         Defaults to ``False``.
        concurrency:     Per-source concurrency override; defaults to 3
                         (the Phase 1 locked-in default).
    """

    base_url: str
    email_env: str = "CONFLUENCE_EMAIL"
    token_env: str = "CONFLUENCE_API_TOKEN"
    space_keys: list[str] = field(default_factory=list)
    page_ids: list[str] = field(default_factory=list)
    include_archived: bool = False
    concurrency: int = 3


@dataclass
class ConfluencePage:
    """Normalised representation of a single Confluence page.

    Populated by :class:`PageExtractor.get_full_page` (ATL-11) from the
    raw ``body.storage`` response.  The ``body_storage`` XHTML is the
    authoritative content that the plugin persists byte-for-byte via
    :class:`RawDocument` (``format="html"``).

    ATL-02 only declares the shape; field population lives in ATL-11.
    """

    page_id: str
    title: str
    space_key: str
    version_number: int
    modified_at: datetime
    url: str
    ancestors: list[dict] = field(default_factory=list)  # [{id, title}]
    labels: list[str] = field(default_factory=list)
    body_storage: str = ""  # raw body.storage.value (XHTML)
