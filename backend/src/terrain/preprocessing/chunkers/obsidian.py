from __future__ import annotations

import re

from src.terrain.preprocessing.chunkers.markdown_default import (
    MarkdownDefaultChunker,
    _ordered_union,
)
from src.terrain.utils.models import SourceDocument, TerrainChunk


# In production the reader strips frontmatter before chunking; this is kept
# as defense-in-depth for callers that pass raw content (tests, ad-hoc).
_FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)
# `[[Page]]`, `[[Page|alias]]`, and `![[asset.png]]` all match — the leading
# `!` is outside the capture group, so the same pattern handles page links
# and asset embeds.
_WIKILINK = re.compile(r"\[\[([^\]|\n]+)(?:\|[^\]\n]+)?\]\]")


class ObsidianChunker(MarkdownDefaultChunker):
    """Obsidian-tuned chunker.

    Strips YAML frontmatter (defense-in-depth — the reader normally pre-strips
    it). Extracts `[[wikilinks]]` and asset embeds (`![[asset.png]]`) per
    chunk. Stamps frontmatter `tags:` from `doc.metadata` onto every chunk so
    structured context survives the chunk boundary.
    """

    def _preprocess(self, doc: SourceDocument) -> str:
        return _FRONTMATTER.sub("", doc.content, count=1)

    def _chunks_for_doc(self, doc: SourceDocument) -> list[TerrainChunk]:
        chunks = super()._chunks_for_doc(doc)
        frontmatter_tags = _normalize_frontmatter_tags(doc.metadata.get("tags"))
        out: list[TerrainChunk] = []
        for chunk in chunks:
            wikilinks = _extract_wikilinks(chunk.content)
            updates: dict = {}
            if wikilinks:
                updates["wikilinks"] = _ordered_union(chunk.wikilinks, wikilinks)
            if frontmatter_tags:
                updates["frontmatter_tags"] = frontmatter_tags
            out.append(chunk.model_copy(update=updates) if updates else chunk)
        return out


def _extract_wikilinks(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in _WIKILINK.findall(text):
        target = raw.strip()
        if target and target not in seen:
            seen.add(target)
            out.append(target)
    return out


def _normalize_frontmatter_tags(raw: object) -> list[str]:
    """Frontmatter `tags:` can arrive as list, comma-separated string, or
    single string. Normalize to ``list[str]`` of stripped, deduped tokens."""
    if raw is None:
        return []
    if isinstance(raw, list):
        items = [str(t).strip() for t in raw if str(t).strip()]
    elif isinstance(raw, str):
        items = [t.strip() for t in raw.split(",") if t.strip()]
    else:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for tag in items:
        if tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out
