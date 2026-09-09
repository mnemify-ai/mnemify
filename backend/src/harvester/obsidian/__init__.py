"""Obsidian source plugin — models and public API.

Registers itself with the plugin registry at import time so the CLI can
instantiate it via ``create_plugin("obsidian", config)``.
"""

from .models import ObsidianVaultConfig
from .plugin import ObsidianHarvesterPlugin

__all__ = [
    "ObsidianVaultConfig",
    "ObsidianHarvesterPlugin",
]


# ── Plugin registry self-registration ─────────────────────────────


def _create_obsidian_plugin(config: dict):
    """Factory used by the plugin registry.

    ``config`` is the ``sources.obsidian`` sub-dict from mnemify.yaml
    (or a programmatic dict with at least ``vault_path``).

    Returns ``(plugin, None)`` — Obsidian has no long-lived network client.
    """
    vault_cfg = ObsidianVaultConfig(
        vault_path=config["vault_path"],
        watch_folders=config.get("watch_folders", []),
        ignore_patterns=config.get("ignore_patterns", []),
    )
    return ObsidianHarvesterPlugin(vault_cfg), None


from src.harvester.registry import register_plugin  # noqa: E402

register_plugin("obsidian", _create_obsidian_plugin)
