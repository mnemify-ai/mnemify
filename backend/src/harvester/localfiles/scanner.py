"""Local folder scanner.

Walks a directory tree and yields every file whose extension the plugin can
turn into text (see ``SUPPORTED_EXTENSIONS``). Mirrors the Obsidian vault
scanner's ignore semantics — ``folder/*`` patterns are directory-prefix
checks, everything else goes through ``fnmatch`` — so the two connectors
behave the same way for a user who has both.

Hidden directories (anything starting with ``.``) are skipped wholesale:
``.git``, ``.obsidian``, ``.mnemify``, editor state and OS junk all live
there, and none of it is a document.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
from typing import Iterator

from .models import LocalRoot

logger = logging.getLogger(__name__)

#: Extension → the ``RawDocument.format`` the plugin stamps on the file.
#: Markdown and plain text pass through; PDF goes through text extraction in
#: ``normalize``. Keep this the single place that decides what "supported"
#: means — the wizard's validate route reports its count from here too.
SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".md": "md",
    ".markdown": "md",
    ".txt": "txt",
    ".text": "txt",
    ".pdf": "pdf",
}

#: Scope entries that name a single file rather than a folder carry this
#: prefix (``file:notes/todo.txt``). Same string the discover route uses for
#: file items, so a picked file round-trips into ``watch_folders`` unchanged.
FILE_SCOPE_PREFIX = "file:"

#: Always ignored, regardless of user config. Root-relative directory
#: prefixes or fnmatch patterns.
DEFAULT_IGNORE: list[str] = [
    ".mnemify/*",
    "node_modules/*",
    "__pycache__/*",
    ".venv/*",
    "venv/*",
]


def format_for(path: Path) -> str | None:
    """The raw format for ``path``, or ``None`` when the extension is unsupported."""
    return SUPPORTED_EXTENSIONS.get(path.suffix.lower())


class FolderScanner:
    """Walks a folder and yields supported, non-ignored file paths."""

    def __init__(self, root_path: Path, root: LocalRoot) -> None:
        self.root_path = root_path
        self.watch_folders: list[str] = list(root.watch_folders)
        self.ignore_patterns: list[str] = DEFAULT_IGNORE + list(root.ignore_patterns)

    def scan(self) -> Iterator[Path]:
        """Yield every supported file that passes the ignore filter.

        With ``watch_folders`` set only those subtrees are walked, plus any
        ``file:`` entries as single files; otherwise the whole root. Symlinks
        are never followed, so a loop in the user's folder cannot hang the
        harvest.
        """
        roots: list[Path] = []
        singles: list[Path] = []
        if self.watch_folders:
            for entry in self.watch_folders:
                if entry.startswith(FILE_SCOPE_PREFIX):
                    singles.append(self.root_path / entry[len(FILE_SCOPE_PREFIX):])
                else:
                    roots.append(self.root_path / entry)
        else:
            roots = [self.root_path]

        seen = 0
        yielded = 0
        emitted: set[Path] = set()
        for path in singles:
            if not path.is_file() or path.is_symlink() or format_for(path) is None:
                logger.warning(f"FolderScanner: scoped file missing or unsupported, skipping: {path}")
                continue
            try:
                relative = path.relative_to(self.root_path).as_posix()
            except ValueError:
                continue
            if self._is_ignored(relative):
                continue
            emitted.add(path)
            yielded += 1
            yield path
        for root in roots:
            if not root.is_dir():
                logger.warning(f"FolderScanner: watch folder missing, skipping: {root}")
                continue
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                # Prune hidden directories in place so os.walk never descends.
                dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                for name in sorted(filenames):
                    if name.startswith("."):
                        continue
                    path = Path(dirpath) / name
                    if format_for(path) is None:
                        continue
                    if path.is_symlink():
                        continue
                    seen += 1
                    try:
                        relative = path.relative_to(self.root_path).as_posix()
                    except ValueError:
                        continue
                    if self._is_ignored(relative):
                        continue
                    if path in emitted:
                        continue  # also picked individually
                    emitted.add(path)
                    yielded += 1
                    yield path

        logger.debug(
            f"FolderScanner: {yielded} files yielded ({seen - yielded} ignored) "
            f"from {self.root_path.name}"
        )

    def _is_ignored(self, relative_posix: str) -> bool:
        for pattern in self.ignore_patterns:
            if pattern.endswith("/*"):
                dir_prefix = pattern[:-2]
                if relative_posix == dir_prefix or relative_posix.startswith(dir_prefix + "/"):
                    return True
            elif fnmatch.fnmatch(relative_posix, pattern):
                return True
        return False
