"""Slack plugin data models.

:class:`SlackConfig` is the schema the YAML ``sources.slack`` block parses
into; :class:`ChannelSpec` is the per-channel sub-record used by the
``channels:`` list.

Auth-related decisions:

- User token (``xoxp-``) only — bot tokens see only channels the bot is
  invited to, which doesn't match the personal knowledge-map use case. The user
  creates a Slack App in their own workspace, adds these User Token Scopes
  (user-scope, not bot-scope), and installs to themselves:
  ``channels:history``, ``channels:read``, ``groups:history``, ``groups:read``,
  ``im:history``, ``im:read``, ``mpim:history``, ``mpim:read``, ``users:read``,
  ``files:read``, ``team:read``. Private channels additionally require the
  user to be a member — user tokens inherit the Slack client's membership.
- The token comes from the env var named by ``token_env`` (default
  ``SLACK_USER_TOKEN``) — same pattern as the Notion plugin.

Document-model decisions:

- Two emission modes drive distinct ``source_id`` namespaces so the
  ``both`` mode never produces collisions:
  ``slack:{channel_id}:thread:{thread_ts}`` for thread-as-doc, and
  ``slack:{channel_id}:summary:{YYYY-MM-DD}`` for daily channel summaries.
- Per-channel ``mode`` overrides ``document_mode_default`` so users can
  pick threads-only for some channels and full coverage for others.
- ``past_days`` bounds first-run history walks; the orchestrator's
  manifest-driven ``since`` filter handles incremental subsequent runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DocumentMode = Literal["thread", "channel_summary", "both"]
SummaryWindow = Literal["day", "week"]


@dataclass
class ChannelSpec:
    """A single entry under ``sources.slack.channels`` in the YAML.

    Attributes:
        id: Slack conversation ID (``C…`` public channel, ``G…`` private
            channel, ``D…`` direct message, ``MPDM…`` multi-person DM).
            User must be a member of the channel for the user token to
            see it.
        mode: Per-channel override of :attr:`SlackConfig.document_mode_default`.
            ``None`` means inherit the default.
        past_days: Per-channel override of :attr:`SlackConfig.past_days`.
            Useful for low-value DMs you want a tight window on, or
            high-value channels you want a longer history of.
    """

    id: str
    mode: DocumentMode | None = None
    past_days: int | None = None


@dataclass
class SlackConfig:
    """Configuration for the Slack harvester.

    Matches the ``sources.slack`` block of ``mnemify.yaml`` 1:1.

    Attributes:
        token_env: Name of the env var holding the User OAuth Token
            (``xoxp-…``). Default ``SLACK_USER_TOKEN``.
        channels: Allowlist of channels / DMs / group DMs to harvest.
            Required — there is no "harvest everything" mode by design;
            mirrors how Confluence requires ``space_keys`` and Jira
            requires ``project_keys``.
        document_mode_default: Default emission mode applied to any
            channel without a ``mode`` override. ``thread`` is the safest
            starting choice (high signal, low volume).
        past_days: First-run history cutoff in days; on subsequent runs
            the manifest's last-completed-run timestamp narrows the
            window. DMs especially benefit from a bounded first walk —
            a years-old DM channel can yield 10k+ messages otherwise.
        summary_window: Bucket size for ``channel_summary`` mode.
            Currently only ``day`` is implemented; ``week`` is reserved
            for V1.1.
        name_cache_ttl_seconds: How long the in-process user/channel
            name cache holds positive entries before re-fetching.
        concurrency: Per-source concurrency override; defaults to 3 to
            match the other API-bound plugins and to stay under Slack's
            Tier 3 rate limit (``conversations.history`` ~50/min).
    """

    channels: list[ChannelSpec]
    token_env: str = "SLACK_USER_TOKEN"
    document_mode_default: DocumentMode = "thread"
    past_days: int = 90
    summary_window: SummaryWindow = "day"
    name_cache_ttl_seconds: int = 3600
    concurrency: int = 3
