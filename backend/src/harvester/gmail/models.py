"""Gmail plugin data models.

Mirrors the shape of :mod:`src.harvester.jira.models` — :class:`GmailConfig`
is the schema the YAML ``sources.gmail`` block parses into, and the file is
intentionally small because the bulk of Gmail-shaped data lives in the raw
thread JSON envelope rather than in a typed in-memory structure.

OAuth-related decisions:

- Credentials are an OAuth client-secret JSON file from a Google Cloud
  project (see ``backend/docs/planning/phase-2-roadmap.md`` §4 — alpha
  uses a chmod-protected JSON file; OS keychain integration is deferred).
  The path is read from the env var named by ``credentials_env`` so users
  can keep the file outside the repo.
- The cached refresh-token JSON written by ``mnemify login --source gmail``
  lives at ``token_path`` (defaults to ``~/.mnemify/gmail/token.json``).
- Default volume filtering excludes promotional / social labels — those
  inboxes contribute almost no work-context value but dominate raw
  message counts on most accounts. Users override via ``mnemify.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GmailConfig:
    """Configuration for the Gmail harvester.

    Matches the ``sources.gmail`` block of ``mnemify.yaml`` 1:1.

    Attributes:
        credentials_env: Power-user override — name of the env var that
            holds the absolute path to a custom Google OAuth client-secret
            JSON file. Most users leave this alone; the harvester falls
            back to the Mnemify-shipped OAuth client at
            ``backend/src/harvester/_google/oauth_client.json``.
        token_path: Path to the cached refresh-token JSON written by
            ``mnemify login --source gmail`` on first authorisation.
            ``~``-expansion is honoured at load time. Default groups
            Gmail's token next to other Google service tokens (Drive,
            Calendar, ...) so they share one OS-level directory.
        label_filter: Optional include-list of Gmail label names. Empty
            means "every label" — only ``label_exclude`` filters apply.
        label_exclude: Default-on exclude list. The Phase-2 default skips
            ``CATEGORY_PROMOTIONS`` and ``CATEGORY_SOCIAL`` because those
            categories are dense in volume and sparse in work context.
        sender_allowlist: Optional include-list of sender addresses to
            restrict the harvest to (e.g. specific clients or teammates).
            Empty means "every sender".
        max_threads_per_run: Optional safety cap. ``None`` runs unbounded;
            useful for the first run on a new account where you want to
            sample 200 threads before committing to the full backfill.
        concurrency: Per-source concurrency override; defaults to 3 to
            match the other API-bound plugins.
        user_id: The Gmail user identifier — ``"me"`` resolves to the
            authenticated account. Override only if you ever need to act
            on a delegated mailbox (out of scope for the alpha).
    """

    credentials_env: str = "GMAIL_CREDENTIALS_PATH"
    token_path: str = "~/.mnemify/google/gmail-token.json"
    label_filter: list[str] = field(default_factory=list)
    label_exclude: list[str] = field(
        default_factory=lambda: ["CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL"]
    )
    sender_allowlist: list[str] = field(default_factory=list)
    max_threads_per_run: int | None = None
    concurrency: int = 3
    user_id: str = "me"
