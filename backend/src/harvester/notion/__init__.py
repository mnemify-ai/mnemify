"""Notion source plugin — models and public API.

Registers itself with the plugin registry at import time so the CLI can
instantiate it via ``create_plugin("notion", config)``.
"""

from .models import (
    NotionAttachment,
    NotionBlock,
    NotionDatabase,
    NotionDatabaseRow,
    NotionPage,
)
from .client import NotionClient
from .pages import AttachmentExtractor, PageExtractor
from .databases import DatabaseExtractor
from .plugin import NotionHarvesterPlugin

__all__ = [
    # Models
    "NotionPage",
    "NotionBlock",
    "NotionDatabase",
    "NotionDatabaseRow",
    "NotionAttachment",
    # Extractors
    "NotionClient",
    "PageExtractor",
    "AttachmentExtractor",
    "DatabaseExtractor",
    # Plugin
    "NotionHarvesterPlugin",
]


# ── Plugin registry self-registration ─────────────────────────────


def _create_notion_plugin(config: dict):
    """Factory used by the plugin registry.

    ``config`` is the ``sources.notion`` sub-dict from mnemify.yaml (or a
    programmatic dict with at least a Notion token or ``token_env`` key).

    Returns ``(plugin, client)`` — the client must be closed by the caller.
    """
    import os

    token_env = config.get("token_env", "NOTION_TOKEN")
    token = config.get("token") or os.getenv(token_env, "")
    if not token or token.startswith("ntn_your_"):
        raise EnvironmentError(
            f"Notion token not found. Set the {token_env!r} environment variable "
            "or provide 'token' directly in the source config."
        )
    # Tunables (with safe defaults). Override in mnemify.yaml under
    # ``sources.notion`` to trade safety for speed:
    #   rate_buffer: 0.05  → uses 95 % of Notion's 3 req/s cap
    #   fetch_comments: false → skip the per-page comments call
    rate_buffer = float(config.get("rate_buffer", 0.15))
    fetch_comments = bool(config.get("fetch_comments", False))
    # ``scope``: list of Notion object ids the connection wizard selected
    # (pages/databases to harvest, and their subtrees). Absent/empty →
    # harvest everything the integration can see.
    scope = config.get("scope") or []

    client = NotionClient(token=token, rate_buffer=rate_buffer)
    plugin = NotionHarvesterPlugin(
        client, fetch_comments=fetch_comments, scope=scope
    )
    return plugin, client


from src.harvester.registry import register_plugin  # noqa: E402

register_plugin("notion", _create_notion_plugin)
