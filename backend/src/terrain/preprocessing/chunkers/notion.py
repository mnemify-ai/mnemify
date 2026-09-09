from __future__ import annotations

import re

from src.terrain.preprocessing.chunkers.markdown_default import MarkdownDefaultChunker
from src.terrain.utils.models import SourceDocument, TerrainChunk


# Notion's markdown renderer (harvester/notion/pages.py::blocks_to_markdown) emits
# distinctive markers for child_page and child_database blocks:
#   - 📄 Page Title
#   - 🗄 Database Title
# These are navigation references, not semantic content — the actual child-page
# content lives in its own SourceDocument. Keeping the markers in the parent's
# body confuses the extractor (long lists of child-page link lines look like
# meaningful content but carry zero information beyond the title).
_CHILD_PAGE_LINE = re.compile(r"^\s*-\s+(?:📄|🗄)\s+.+$")


class NotionChunker(MarkdownDefaultChunker):
    """Notion-tuned chunker.

    Strips navigation-only block markers (child_page / child_database) that
    Notion's markdown renderer emits in the parent doc. Stamps Notion page
    properties (status, assignees, dates, …) onto every chunk via
    `source_properties` so the extractor and embedder see them.
    """

    def _preprocess(self, doc: SourceDocument) -> str:
        kept: list[str] = []
        for line in doc.content.splitlines():
            if _CHILD_PAGE_LINE.match(line):
                continue
            kept.append(line)
        return "\n".join(kept)

    def _chunks_for_doc(self, doc: SourceDocument) -> list[TerrainChunk]:
        chunks = super()._chunks_for_doc(doc)
        properties = doc.metadata.get("properties") or {}
        if not isinstance(properties, dict) or not properties:
            return chunks
        return [chunk.model_copy(update={"source_properties": properties}) for chunk in chunks]
