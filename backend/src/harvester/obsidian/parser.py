"""Obsidian markdown parser — frontmatter extraction and attachment discovery.

Two responsibilities:

1. ``peek_frontmatter(path)`` — read only enough of a file to extract the
   YAML frontmatter and title without loading the full document into memory.
   Used by ``list_documents()`` for the lightweight DocRef pass.

2. ``find_attachments(content, vault_path, note_dir)`` — scan a note's body
   for ``![[filename]]`` embed syntax and resolve each reference to an
   absolute filesystem path.

The ``python-frontmatter`` library is used for robust YAML parsing.  If it
is not installed, an ImportError is raised with a helpful message.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Regex for Obsidian's wikilink embed syntax: ![[target]] or ![[target|alias]]
_EMBED_RE = re.compile(r"!\[\[([^\]]+)\]\]")

# File extensions the harvester considers to be harvestable attachments.
# Images, documents, and common data files included; source code excluded.
ATTACHMENT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".mp3", ".mp4", ".mov", ".wav", ".ogg",
        ".zip", ".csv", ".json", ".xml",
    }
)


class NoteParser:
    """Parse Obsidian markdown files for metadata and attachment references."""

    # ── Frontmatter ────────────────────────────────────────────────

    def peek_frontmatter(self, file_path: Path) -> tuple[str | None, dict]:
        """Extract the title and frontmatter metadata from a file.

        Reads the file fully but only parses the YAML header.  Returns
        ``(title, metadata_dict)`` where ``title`` is either the frontmatter
        ``title`` field or ``None`` (caller falls back to the file stem).

        On any parse or I/O error, logs a warning and returns ``(None, {})``.
        """
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning(f"Could not read {file_path}: {e}")
            return None, {}

        return self._parse_frontmatter(content)

    def _parse_frontmatter(self, content: str) -> tuple[str | None, dict]:
        """Internal: parse frontmatter from a string, return (title, metadata)."""
        try:
            import frontmatter  # python-frontmatter
        except ImportError as exc:
            raise ImportError(
                "python-frontmatter is required for Obsidian frontmatter parsing. "
                "Install it with: pip install python-frontmatter"
            ) from exc

        try:
            post = frontmatter.loads(content)
            metadata: dict = dict(post.metadata)
            title: str | None = metadata.get("title") or None
            # Normalize tags to a list of strings
            tags = metadata.get("tags", [])
            if isinstance(tags, str):
                metadata["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
            elif not isinstance(tags, list):
                metadata["tags"] = []
            key_count = len(metadata)
            logger.debug(
                f"NoteParser: parsed frontmatter — title={title!r}, "
                f"{key_count} keys, {len(metadata.get('tags', []))} tags"
            )
            return title, metadata
        except Exception as e:
            logger.warning(f"NoteParser: frontmatter parse error — {e}")
            return None, {}

    def strip_frontmatter(self, content: str) -> str:
        """Return the body of a note with the YAML frontmatter removed.

        Uses the same ``---`` delimiter detection as Obsidian.  If no
        frontmatter is found, returns the original content unchanged.
        """
        if not content.startswith("---"):
            return content
        end = content.find("---", 3)
        if end == -1:
            return content
        # Skip past the closing delimiter and any leading blank lines
        return content[end + 3:].lstrip()

    # ── Attachment discovery ───────────────────────────────────────

    def find_attachments(
        self,
        content: str,
        vault_path: Path,
        note_dir: Path,
    ) -> list:
        """Find embedded attachment references in a note's markdown body.

        Scans for ``![[filename]]`` syntax and resolves each reference to an
        absolute path using Obsidian's resolution order:

        1. Exact path relative to vault root.
        2. Relative to the note's directory.
        3. Shortest-path match anywhere in the vault (Obsidian's default for
           unqualified filenames — scanned lazily, first match wins).

        Only returns references that resolve to existing files whose extension
        is in ``ATTACHMENT_EXTENSIONS``.

        Returns a list of ``AttachmentRef`` dataclasses (imported at use-time
        to avoid circular imports at module level).
        """
        from src.harvester import AttachmentRef

        refs: list[AttachmentRef] = []
        seen_paths: set[str] = set()
        embed_count = 0

        for match in _EMBED_RE.finditer(content):
            embed_count += 1
            raw_ref = match.group(1).split("|")[0].strip()  # strip display alias
            # Strip display text after #heading if present
            raw_ref = raw_ref.split("#")[0].strip()

            resolved = self._resolve_attachment(raw_ref, vault_path, note_dir)
            if resolved is None:
                logger.debug(f"NoteParser: attachment not resolved: {raw_ref!r}")
                continue
            if resolved.suffix.lower() not in ATTACHMENT_EXTENSIONS:
                logger.debug(
                    f"NoteParser: skipping embed with non-attachment extension: "
                    f"{resolved.name}"
                )
                continue

            resolved_str = str(resolved)
            if resolved_str in seen_paths:
                logger.debug(f"NoteParser: deduplicating attachment: {resolved.name}")
                continue
            seen_paths.add(resolved_str)

            mime_type = _guess_mime(resolved.suffix)
            att_id = hashlib.sha256(resolved_str.encode()).hexdigest()[:16]
            logger.debug(
                f"NoteParser: resolved attachment {raw_ref!r} -> {resolved.name} "
                f"(mime={mime_type})"
            )
            refs.append(
                AttachmentRef(
                    source_id=att_id,
                    filename=resolved.name,
                    url=resolved_str,
                    mime_type=mime_type,
                )
            )

        logger.debug(
            f"NoteParser: find_attachments — {embed_count} embeds found, "
            f"{len(refs)} resolved"
        )
        return refs

    def _resolve_attachment(
        self,
        raw_ref: str,
        vault_path: Path,
        note_dir: Path,
    ) -> Path | None:
        """Resolve a raw ``![[ref]]`` string to an absolute path.

        Resolution order (mirrors Obsidian):
        1. Exact path relative to vault root.
        2. Relative to the note's containing directory.
        3. Shortest-path match anywhere in the vault (for unqualified names).

        Returns ``None`` if the file cannot be located.
        """
        # The ref is text somebody typed into a note. ``vault_path / "/etc/x"``
        # is ``/etc/x`` (an absolute right-hand side discards the left) and
        # ``..`` walks up freely, so every hit is checked to be a real file
        # *inside* the vault after symlinks are resolved. Anything else is
        # treated as unresolved — the harvester must never copy a file from
        # outside the vault into the data dir because a note pointed at it.
        vault_root = vault_path.resolve()

        def _inside(candidate: Path) -> Path | None:
            try:
                if not (candidate.exists() and candidate.is_file()):
                    return None
                resolved = candidate.resolve()
                if not resolved.is_relative_to(vault_root):
                    logger.warning(
                        f"NoteParser._resolve: {raw_ref!r} points outside the vault; ignored"
                    )
                    return None
                return resolved
            except OSError:
                return None

        if Path(raw_ref).is_absolute():
            logger.warning(f"NoteParser._resolve: absolute embed {raw_ref!r} ignored")
            return None

        # 1. Exact path from vault root
        hit = _inside(vault_path / raw_ref)
        if hit is not None:
            logger.debug(f"NoteParser._resolve: tier-1 (vault-root) hit for {raw_ref!r}")
            return hit

        # 2. Relative to the note's directory
        hit = _inside(note_dir / raw_ref)
        if hit is not None:
            logger.debug(f"NoteParser._resolve: tier-2 (note-dir) hit for {raw_ref!r}")
            return hit

        # 3. Shortest-path match: scan vault for any file with this name/path
        #    Only the filename portion of raw_ref is used for matching here
        #    (Obsidian resolves unqualified names by shortest unique path).
        target_name = Path(raw_ref).name
        best: Path | None = None
        best_depth: int = 9999
        try:
            for candidate in vault_path.rglob(target_name):
                if _inside(candidate) is not None:
                    depth = len(candidate.relative_to(vault_path).parts)
                    if depth < best_depth:
                        best = candidate
                        best_depth = depth
        except OSError:
            pass
        if best is not None:
            logger.debug(
                f"NoteParser._resolve: tier-3 (vault-scan) hit for {raw_ref!r} "
                f"-> {best.relative_to(vault_path).as_posix()}"
            )
            return _inside(best)

        logger.debug(f"NoteParser._resolve: unresolved {raw_ref!r}")
        return None


def _guess_mime(suffix: str) -> str | None:
    """Return a MIME type string for a file extension, or None if unknown."""
    mime, _ = mimetypes.guess_type(f"file{suffix}")
    return mime
