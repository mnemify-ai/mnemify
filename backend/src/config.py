"""Shared configuration — loads environment variables and provides typed access."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from src import paths


def load_config(env_path: Path | None = None, *, override: bool = False) -> None:
    """Load the ``.env`` file into ``os.environ``.

    Reads ``paths.env_file()`` — the same file ``credential_store`` writes —
    so the wizard's saved tokens and the harvester's reads can never point
    at different files. ``override=True`` makes file values replace
    already-set process env (used after a UI write to pick up new values).
    """
    load_dotenv(env_path or paths.env_file(), override=override)


def get_notion_token() -> str:
    """Return the Notion integration token or raise with a helpful message."""
    token = os.getenv("NOTION_TOKEN")
    if not token or token.startswith("ntn_your_"):
        raise EnvironmentError(
            "NOTION_TOKEN not set. "
            "Connect Notion in the app (Build → Sources) or set it in Settings → AI & Models. "
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
