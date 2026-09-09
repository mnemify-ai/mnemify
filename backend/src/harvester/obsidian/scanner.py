"""Obsidian vault filesystem scanner.

Walks the vault directory tree, yielding markdown file paths that pass
the configured ignore rules.  The scanner is synchronous because filesystem
operations are cheap enough not to warrant async overhead, and the caller
(the plugin) wraps it in an async method.

Ignore pattern matching uses simple prefix checks for directory patterns
(``templates/*`` → skip the entire ``templates/`` folder) and ``fnmatch``
for file-level patterns.  This mirrors Obsidian's own exclusion behaviour,
which is folder-first and path-based, not full glob.
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Iterator

from .models import ObsidianVaultConfig

logger = logging.getLogger(__name__)

# Built-in patterns that are always ignored regardless of user config.
# These are vault-relative path prefixes (directories) or fnmatch patterns.
DEFAULT_IGNORE: list[str] = [
    ".obsidian/*",
    ".mnemify/*",
    ".trash/*",
    ".Trash/*",
    "node_modules/*",
]


class VaultScanner:
    """Walks an Obsidian vault and yields non-ignored ``.md`` file paths."""

    def __init__(self, vault_path: Path, config: ObsidianVaultConfig) -> None:
        self.vault_path = vault_path
        self.watch_folders: list[str] = list(config.watch_folders)
        # Merge built-in defaults with user-supplied patterns
        self.ignore_patterns: list[str] = DEFAULT_IGNORE + list(config.ignore_patterns)

    def scan(self) -> Iterator[Path]:
        """Yield all ``.md`` files that pass the ignore filter.

        If ``watch_folders`` is configured, only subtrees under those
        vault-relative folders are walked.  Otherwise the entire vault is
        walked.

        Symlinks are followed only one level deep (``follow_symlinks=False``
        on ``rglob`` is not available in Python < 3.13, so we skip symlink
        entries manually to avoid loops).
        """
        roots: list[Path]
        if self.watch_folders:
            roots = [self.vault_path / folder for folder in self.watch_folders]
            logger.debug(
                f"VaultScanner: restricting to watch_folders={self.watch_folders}"
            )
        else:
            roots = [self.vault_path]
            logger.debug("VaultScanner: scanning entire vault")

        total_seen = 0
        total_yielded = 0

        for root in roots:
            if not root.exists():
                logger.warning(f"Watch folder does not exist, skipping: {root}")
                continue
            if not root.is_dir():
                logger.warning(f"Watch folder is not a directory, skipping: {root}")
                continue

            logger.debug(f"VaultScanner: walking {root}")
            for md_file in root.rglob("*.md"):
                # Skip symlinks to avoid loops in vaults that use them
                if md_file.is_symlink():
                    logger.debug(f"VaultScanner: skipping symlink {md_file}")
                    continue
                total_seen += 1
                try:
                    relative = md_file.relative_to(self.vault_path).as_posix()
                except ValueError:
                    # File is outside the vault root (should not happen with rglob)
                    logger.warning(f"VaultScanner: file outside vault root, skipping: {md_file}")
                    continue

                if self._is_ignored(relative):
                    logger.debug(f"VaultScanner: ignored {relative}")
                else:
                    total_yielded += 1
                    yield md_file

        logger.debug(
            f"VaultScanner: scan complete — {total_yielded} notes yielded "
            f"({total_seen - total_yielded} ignored) from {self.vault_path.name}"
        )

    def _is_ignored(self, relative_posix: str) -> bool:
        """Return True if the vault-relative path matches any ignore pattern.

        Patterns ending with ``/*`` are treated as directory prefix checks:
        ``templates/*`` matches any file inside the ``templates/`` folder.
        All other patterns are matched with ``fnmatch.fnmatch``.
        """
        for pattern in self.ignore_patterns:
            if pattern.endswith("/*"):
                # Directory prefix: ignore anything under this folder
                dir_prefix = pattern[:-2]  # strip the /*
                if relative_posix == dir_prefix or relative_posix.startswith(dir_prefix + "/"):
                    return True
            else:
                if fnmatch.fnmatch(relative_posix, pattern):
                    return True
        return False
