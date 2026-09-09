"""Slack source plugin — public API and registry self-registration.

Mirrors the Jira and Gmail plugin shapes. The factory reads the
``sources.slack`` block from ``mnemify.yaml`` and constructs a
:class:`SlackHarvesterPlugin` with a pre-configured :class:`SlackClient`.

Token resolution: the env var named by ``token_env`` (default
``SLACK_USER_TOKEN``). Missing-token raises :class:`EnvironmentError`
at factory time so the operator gets a clear remediation pointer.

Output-format contract: pure-body markdown (Confluence/Gmail pattern).
All structured metadata flows through ``RawDocument.metadata`` to the
manifest's ``documents.metadata`` JSON column. The .md file's first
line is ``# {root author} in #channel: {preview}`` (thread mode) or
``# #channel — {YYYY-MM-DD} (N messages, M people)`` (summary mode).
"""

from __future__ import annotations

import os

from .client import SlackAPIError, SlackAuthError, SlackClient
from .models import ChannelSpec, SlackConfig
from .names import NameCache
from .normalizer import slack_summary_to_markdown, slack_thread_to_markdown
from .plugin import SlackHarvesterPlugin
from .threads import MessageExtractor

__all__ = [
    "SlackConfig",
    "ChannelSpec",
    "SlackClient",
    "SlackAPIError",
    "SlackAuthError",
    "MessageExtractor",
    "NameCache",
    "SlackHarvesterPlugin",
    "slack_thread_to_markdown",
    "slack_summary_to_markdown",
]


# ── Plugin registry self-registration ─────────────────────────────


def _create_slack_plugin(config: dict) -> tuple[SlackHarvesterPlugin, None]:
    """Factory used by the plugin registry.

    ``config`` is the ``sources.slack`` sub-dict from mnemify.yaml.
    Returns ``(plugin, None)`` — matching the Jira/Gmail convention.
    Client teardown lives in :meth:`SlackHarvesterPlugin.aclose`, which
    the orchestrator always calls in its ``finally`` block.
    """
    raw_channels = config.get("channels", []) or []
    channels: list[ChannelSpec] = []
    for entry in raw_channels:
        if isinstance(entry, str):
            channels.append(ChannelSpec(id=entry))
        elif isinstance(entry, dict):
            channels.append(ChannelSpec(
                id=entry["id"],
                mode=entry.get("mode"),
                past_days=entry.get("past_days"),
            ))
        else:
            raise ValueError(f"sources.slack.channels entry must be str or dict, got {type(entry).__name__}")

    cfg = SlackConfig(
        token_env=config.get("token_env", "SLACK_USER_TOKEN"),
        channels=channels,
        document_mode_default=config.get("document_mode_default", "thread"),
        past_days=int(config.get("past_days", 90)),
        summary_window=config.get("summary_window", "day"),
        name_cache_ttl_seconds=int(config.get("name_cache_ttl_seconds", 3600)),
        concurrency=int(config.get("concurrency", 3)),
    )

    token = os.environ.get(cfg.token_env, "").strip()
    if not token:
        raise EnvironmentError(
            f"Slack token not found: env var {cfg.token_env!r} is unset or empty. "
            f"Set it in backend/.env to a User OAuth Token (xoxp-…). "
            f"See backend/.env.template for the Slack App setup steps."
        )

    client = SlackClient(token=token)
    plugin = SlackHarvesterPlugin(cfg, client=client)
    return plugin, None


# Imported here (not at module top) so the registry import order doesn't
# matter — registration is the side-effect of importing this package.
from src.harvester.registry import register_plugin  # noqa: E402

register_plugin("slack", _create_slack_plugin)
