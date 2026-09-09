from __future__ import annotations

from src.terrain.preprocessing.chunkers.confluence import ConfluenceChunker
from src.terrain.preprocessing.chunkers.markdown_default import MarkdownDefaultChunker
from src.terrain.preprocessing.chunkers.notion import NotionChunker
from src.terrain.preprocessing.chunkers.obsidian import ObsidianChunker
from src.terrain.utils.models import SourceDocument, TerrainChunk


class ChunkerRegistry:
    """Dispatches each document to the chunker tuned for its source_type.

    Unregistered source_types fall back to MarkdownDefaultChunker, so any
    source the harvester adds keeps chunking without further code changes
    until a per-source strategy is worth writing.
    """

    def __init__(
        self,
        min_words: int = 120,
        target_words: int = 900,
        max_words: int = 1400,
    ):
        kwargs = {
            "min_words": min_words,
            "target_words": target_words,
            "max_words": max_words,
        }
        self._default = MarkdownDefaultChunker(**kwargs)
        self._chunkers: dict[str, MarkdownDefaultChunker] = {
            "notion": NotionChunker(**kwargs),
            "obsidian": ObsidianChunker(**kwargs),
            "confluence": ConfluenceChunker(**kwargs),
        }

    def register(self, source_type: str, chunker: MarkdownDefaultChunker) -> None:
        self._chunkers[source_type] = chunker

    def for_source(self, source_type: str) -> MarkdownDefaultChunker:
        return self._chunkers.get(source_type, self._default)

    def chunk(self, documents: list[SourceDocument]) -> list[TerrainChunk]:
        out: list[TerrainChunk] = []
        for doc in documents:
            out.extend(self.for_source(doc.source_type).chunk([doc]))
        return out
