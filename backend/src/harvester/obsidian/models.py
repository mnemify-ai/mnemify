"""Obsidian plugin data models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ObsidianVaultConfig:
    """Configuration for the Obsidian vault harvester.

    ``vault_path`` is the only required field.  Everything else has
    sensible defaults that harvest the entire vault.

    Attributes:
        vault_path:      Absolute path to the Obsidian vault root directory.
                         The directory must contain a ``.obsidian/`` sub-folder.
        watch_folders:   If non-empty, only markdown files under these
                         vault-relative folder prefixes are harvested.
                         Empty list means "harvest the entire vault".
        ignore_patterns: Additional glob-style patterns (relative to vault
                         root) to exclude.  Merged with the scanner's built-in
                         DEFAULT_IGNORE list.
    """

    vault_path: str
    watch_folders: list[str] = field(default_factory=list)
    ignore_patterns: list[str] = field(default_factory=list)
