"""Source-aware chunking — dispatcher + per-source strategies."""

from src.terrain.preprocessing.chunkers.confluence import ConfluenceChunker
from src.terrain.preprocessing.chunkers.markdown_default import MarkdownDefaultChunker
from src.terrain.preprocessing.chunkers.notion import NotionChunker
from src.terrain.preprocessing.chunkers.obsidian import ObsidianChunker
from src.terrain.preprocessing.chunkers.registry import ChunkerRegistry

__all__ = [
    "ChunkerRegistry",
    "ConfluenceChunker",
    "MarkdownDefaultChunker",
    "NotionChunker",
    "ObsidianChunker",
]
