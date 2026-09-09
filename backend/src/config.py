"""Shared configuration — loads environment variables and provides typed access."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def load_config(env_path: Path | None = None) -> None:
    """Load .env file. Call once at startup."""
    if env_path:
        load_dotenv(env_path)
    else:
        # Walk up from cwd to find .env
        load_dotenv()


def get_notion_token() -> str:
    """Return the Notion integration token or raise with a helpful message."""
    token = os.getenv("NOTION_TOKEN")
    if not token or token.startswith("ntn_your_"):
        raise EnvironmentError(
            "NOTION_TOKEN not set. "
            "Copy .env.template to .env and add your Notion integration token. "
            "Get one at: https://www.notion.so/my-integrations"
        )
    return token


def get_obsidian_config(source_cfg: dict) -> dict:
    """Return the Obsidian source configuration dict.

    ``source_cfg`` is the ``sources.obsidian`` sub-dict from the YAML config
    file (or an empty dict if not configured).  This function resolves
    ``vault_path`` — required — and returns it along with other settings.

    Raises:
        EnvironmentError: If ``vault_path`` is not set in source_cfg.
    """
    vault_path = source_cfg.get("vault_path", "")
    if not vault_path:
        raise EnvironmentError(
            "Obsidian vault_path is not configured. "
            "Add 'vault_path: /path/to/your/vault' under 'sources.obsidian' "
            "in your mnemify.yaml."
        )
    return {
        "vault_path": str(vault_path),
        "watch_folders": source_cfg.get("watch_folders", []),
        "ignore_patterns": source_cfg.get("ignore_patterns", []),
    }
