from __future__ import annotations

import re
from collections import Counter

from src.terrain.utils.models import ChunkFeatures, TerrainChunk, TagType


# Bump this any time ChunkFeatures or its semantics changes so the cache
# key in the compiler re-extracts rather than returning stale-shape data.
# v4: added ChunkFeatures.signals (LLM-drafted attention signals).
# v5: added due_text/due_date to ChunkSignalDraft (deadline extraction).
# v6: heuristic _entities strips sentence-start stopwords ("The", "This", …)
#     so local-mode names/titles stop being built from them.
SCHEMA_VERSION = "v6"


STOPWORDS = {
    "about", "after", "also", "and", "are", "because", "been", "being", "but",
    "can", "could", "for", "from", "has", "have", "into", "not", "our", "that",
    "the", "their", "then", "there", "this", "with", "will", "would", "your",
}

KNOWN_PRODUCTS = ("Docnostic", "Sitelens", "Book Reading")


def products_schema_suffix(products) -> str:
    """Stable cache-key suffix for a *config-declared* product list.

    Folding declared products into the feature cache key means a chunk
    re-extracts when the user changes their declared products. The suffix is
    empty for an empty list, so corpora that declare none keep the bare
    ``SCHEMA_VERSION`` key (no cache invalidation). Only config products belong
    here — derived-from-prior products are intentionally excluded so a growing
    corpus's shifting top-N doesn't thrash every chunk's cache.
    """
    from src.utils.hashing import short_hash

    cleaned = sorted({p.strip().lower() for p in (products or ()) if p and p.strip()})
    if not cleaned:
        return ""
    return ":" + short_hash("|".join(cleaned), 8)


class FeatureExtractor:
    def __init__(self, products=KNOWN_PRODUCTS, *, cache_products=()):
        # ``products`` = all products used at extraction time (config ∪ derived).
        # ``cache_products`` = config-declared only; feeds ``schema_version``.
        self.products = tuple(products)
        self.cache_products = tuple(cache_products)

    @property
    def schema_version(self) -> str:
        # ``local:`` keeps heuristic features apart from every LLM extractor's
        # in the per-chunk feature cache (see the OpenAI/Claude variants).
        return f"local:{SCHEMA_VERSION}{products_schema_suffix(self.cache_products)}"

    def extract_batch(self, chunks: list[TerrainChunk]) -> list[ChunkFeatures | None]:
        # No network — a plain loop keeps the batch interface uniform with the
        # LLM extractors so the enrich path stays mode-agnostic.
        return [self.extract(chunk) for chunk in chunks]

    def extract(self, chunk: TerrainChunk) -> ChunkFeatures:
        text = self._clean(chunk.content)
        products = [p for p in self.products if p.lower() in text.lower()]
        entities = self._entities(text)
        tags = self._tags(text)
        customers = [e for e in entities if e not in products][:5]
        theme, subtopic = self._theme_subtopic(products, customers, tags, entities)
        return ChunkFeatures(
            summary=self._summary(text),
            products=products,
            customers=customers,
            entities=entities[:12],
            tags=tags[:7],
            tag_type_hint=self._tag_type(products, customers),
            theme=theme,
            subtopic=subtopic,
            confidence=0.55 if len(text.split()) < 80 else 0.7,
        )

    def _clean(self, text: str) -> str:
        text = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", text)
        text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)
        return re.sub(r"\s+", " ", text).strip()

    def _summary(self, text: str) -> str:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        summary = " ".join(s for s in sentences[:3] if s).strip()
        return summary[:700] if summary else text[:300]

    def _entities(self, text: str) -> list[str]:
        matches = re.findall(r"\b[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){0,3}\b", text)
        # Capitalized runs are dominated by sentence-start stopwords ("The",
        # "This is", …) — strip stopword tokens off both ends so entity-derived
        # names/titles don't degrade into "The This"-style junk.
        cleaned: list[str] = []
        for m in matches:
            words = m.strip().split()
            while words and words[0].lower() in STOPWORDS:
                words = words[1:]
            while words and words[-1].lower() in STOPWORDS:
                words = words[:-1]
            candidate = " ".join(words)
            if len(candidate) > 2:
                cleaned.append(candidate)
        counts = Counter(cleaned)
        return [name for name, _ in counts.most_common(15)]

    def _tags(self, text: str) -> list[str]:
        words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9-]{3,}\b", text.lower())
        counts = Counter(w for w in words if w not in STOPWORDS)
        return [word for word, _ in counts.most_common(10)]

    def _tag_type(self, products: list[str], customers: list[str]) -> TagType:
        if products:
            return "product"
        if customers:
            return "person"
        return "concept"

    def _theme_subtopic(
        self,
        products: list[str],
        customers: list[str],
        tags: list[str],
        entities: list[str],
    ) -> tuple[str, str]:
        """Local heuristic for (theme, subtopic).

        Theme is the broadest signal; subtopic refines it. The OpenAI
        extractor overrides this with a much stronger LLM-driven guess.
        """
        if products:
            theme = "Products"
            subtopic = products[0].title()
        elif customers:
            theme = "Customer Communication"
            subtopic = customers[0]
        elif tags:
            theme = tags[0].title()
            subtopic = tags[1].title() if len(tags) > 1 else theme
        elif entities:
            theme = entities[0]
            subtopic = entities[1] if len(entities) > 1 else theme
        else:
            theme = "General"
            subtopic = "General"
        return theme[:48], subtopic[:48]


def heuristic_tag_type(features: ChunkFeatures) -> TagType:
    """Fallback used by the OpenAI extractor when the LLM returns an
    out-of-enum value. Mirrors ``FeatureExtractor._tag_type``.
    """
    if features.products:
        return "product"
    if features.customers:
        return "person"
    return "concept"