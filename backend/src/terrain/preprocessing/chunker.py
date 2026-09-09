"""Backwards-compatibility shim.

The chunker now lives at ``src.terrain.preprocessing.chunkers``. Existing
callers and tests that import ``MarkdownChunker`` from here keep working —
the name resolves to the default markdown strategy (source-agnostic).

New callers should import :class:`ChunkerRegistry` from
:mod:`src.terrain.preprocessing.chunkers` instead.
"""

from __future__ import annotations

from src.terrain.preprocessing.chunkers import (
    ChunkerRegistry,
    MarkdownDefaultChunker,
)

# Back-compat alias: the original MarkdownChunker == today's default strategy.
MarkdownChunker = MarkdownDefaultChunker

__all__ = ["ChunkerRegistry", "MarkdownChunker", "MarkdownDefaultChunker"]
