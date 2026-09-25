"""Local files plugin data models.

One source, many folders: a user links every folder they care about
(``~/Notes``, a Downloads sub-folder of PDFs, a shared drive mount) and each
is a ``LocalRoot`` with its own optional scope. Documents are keyed by root
+ relative path, so the same relative path in two roots never collides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: Separates a root from a root-relative scope entry in the flat scope ids
#: the API and the orchestrator trade (``/abs/root::notes``,
#: ``/abs/root::file:notes/todo.txt``, ``/abs/root::`` = the whole root).
SCOPE_SEP = "::"


def root_key(path: str) -> str:
    """Canonical string for a root: expanded, resolved, absolute. Every id
    that names a root (document ids, scope ids) goes through this so a
    ``~`` in YAML and the resolved path in a manifest row still match."""
    return str(Path(path).expanduser().resolve())


@dataclass
class LocalRoot:
    """One linked folder.

    Attributes:
        path:            The folder. Any folder works; no marker file needed.
        watch_folders:   Root-relative sub-folders, and ``file:<relpath>``
                         single files, to harvest. Empty = the whole root.
        ignore_patterns: Extra glob-style excludes, merged with the
                         scanner's built-in DEFAULT_IGNORE.
    """

    path: str
    watch_folders: list[str] = field(default_factory=list)
    ignore_patterns: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return root_key(self.path)

    def scope_ids(self) -> list[str]:
        """This root's entries as flat scope ids; the whole-root id when it
        has no narrowing."""
        if self.watch_folders:
            return [f"{self.key}{SCOPE_SEP}{wf}" for wf in self.watch_folders]
        return [f"{self.key}{SCOPE_SEP}"]


@dataclass
class LocalFilesConfig:
    """Configuration for the local-folder harvester: a list of roots.

    ``LocalFilesConfig(root_path=..., watch_folders=...)`` still works as a
    one-root shorthand (tests, the CLI) — it is folded into ``roots``.
    """

    roots: list[LocalRoot] = field(default_factory=list)
    root_path: str | None = None
    watch_folders: list[str] = field(default_factory=list)
    ignore_patterns: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.root_path:
            self.roots = [
                LocalRoot(
                    path=self.root_path,
                    watch_folders=list(self.watch_folders),
                    ignore_patterns=list(self.ignore_patterns),
                )
            ] + list(self.roots)
            self.root_path = None

    @classmethod
    def from_yaml(cls, block: dict) -> "LocalFilesConfig":
        """Build from the ``sources.localfiles`` YAML block. Accepts the
        multi-root ``roots:`` list and the older single ``root_path:`` form
        (both may be present; the single form becomes the first root)."""
        roots = [
            LocalRoot(
                path=str(r.get("path") or ""),
                watch_folders=list(r.get("watch_folders") or []),
                ignore_patterns=list(r.get("ignore_patterns") or []),
            )
            for r in (block.get("roots") or [])
            if isinstance(r, dict) and r.get("path")
        ]
        return cls(
            roots=roots,
            root_path=block.get("root_path") or None,
            watch_folders=list(block.get("watch_folders") or []),
            ignore_patterns=list(block.get("ignore_patterns") or []),
        )

    def scope_ids(self) -> list[str]:
        out: list[str] = []
        for r in self.roots:
            out.extend(r.scope_ids())
        return out


def split_scope_id(scope_id: str) -> tuple[str, str] | None:
    """``"/abs/root::notes"`` → ``("/abs/root", "notes")``; None if malformed."""
    if SCOPE_SEP not in scope_id:
        return None
    root, entry = scope_id.split(SCOPE_SEP, 1)
    return (root, entry) if root else None


def roots_from_scope_ids(scope_ids: list[str], existing: list[LocalRoot]) -> list[LocalRoot]:
    """Rebuild the roots list from flat scope ids (the Manage Scope dialog
    sends the full picture). Roots not named by any id are dropped; a root
    named only by its whole-root id has no narrowing. ``ignore_patterns``
    are carried over from ``existing`` by root key."""
    keep_ignores = {r.key: r.ignore_patterns for r in existing}
    order: list[str] = []
    entries: dict[str, list[str]] = {}
    for sid in scope_ids:
        parts = split_scope_id(sid)
        if not parts:
            continue
        root, entry = parts
        key = root_key(root)
        if key not in entries:
            entries[key] = []
            order.append(key)
        if entry:
            entries[key].append(entry)
    return [
        LocalRoot(path=key, watch_folders=entries[key], ignore_patterns=list(keep_ignores.get(key, [])))
        for key in order
    ]
