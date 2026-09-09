from __future__ import annotations

from collections import Counter

from src.terrain.utils.models import EnrichedChunk
from src.terrain.utils.store import TerrainStore
from src.utils.hashing import short_hash


class ClusterNamer:
    """Deterministic local fallback namer.

    OpenAI builds use ``OpenAIClusterNamer`` from ``src.terrain.agents``; this
    class is intentionally heuristic for ``ai_mode='local'`` and offline tests.
    """

    def __init__(self, store: TerrainStore):
        self.store = store

    def name_theme(
        self,
        items: list[EnrichedChunk],
        fallback: str = "General",
        *,
        avoid_names: list[str] | None = None,
    ) -> tuple[str, str]:
        """Name a root theme that groups descendant nodes.

        ``avoid_names`` (sibling labels already taken) is accepted for API
        parity with the LLM namers; the heuristic cannot act on it, so the
        compiler's deterministic collision fallback handles duplicates.
        """
        del avoid_names
        fingerprint = self._fingerprint(items, kind="theme")
        cached = self.store.get_name(fingerprint)
        if cached:
            return cached
        products = [item.features.products[0] for item in items if item.features.products]
        if products:
            name, count = Counter(products).most_common(1)[0]
            if count >= max(2, len(items) // 2):
                summary = self._theme_summary(items, name)
                self.store.save_name(fingerprint, name, summary)
                return name[:48], summary
        themes = [item.features.theme for item in items if item.features.theme]
        if themes:
            name = Counter(themes).most_common(1)[0][0][:48]
        else:
            name = self._title(items, fallback, max_words=3)
        summary = self._theme_summary(items, name)
        self.store.save_name(fingerprint, name, summary)
        return name, summary

    def name_region(
        self,
        items: list[EnrichedChunk],
        fallback: str = "Loose Notes",
        *,
        avoid_names: list[str] | None = None,
    ) -> tuple[str, str]:
        del avoid_names  # see name_theme
        fingerprint = self._fingerprint(items, kind="region")
        cached = self.store.get_name(fingerprint)
        if cached:
            return cached
        name = self._title(items, fallback, max_words=3)
        summary = self._region_summary(items, name)
        self.store.save_name(fingerprint, name, summary)
        return name, summary

    def name_tag(
        self,
        items: list[EnrichedChunk],
        fallback: str = "General",
        *,
        region_name: str | None = None,
        region_terms: list[str] | None = None,
    ) -> tuple[str, str]:
        fingerprint = self._fingerprint(
            items,
            kind="tag",
            context=[region_name or "", *(region_terms or [])],
        )
        cached = self.store.get_name(fingerprint)
        if cached:
            return cached
        label = self._title(items, fallback, max_words=2)
        blurb = self._tag_blurb(
            items,
            label,
            region_name=region_name,
            region_terms=region_terms or [],
        )
        self.store.save_name(fingerprint, label, blurb)
        return label, blurb

    # ── fingerprint / title helpers ────────────────────────────────

    def _fingerprint(
        self,
        items: list[EnrichedChunk],
        *,
        kind: str,
        context: list[str] | None = None,
        extra: list[str] | None = None,
    ) -> str:
        """Cache key for a naming call.

        ``context`` joins the feature vocabulary (tags use it for the region
        lens). ``extra`` is hashed verbatim — it exists so a *rename* prompt
        (e.g. ``avoid_names`` after a sibling label collision) can never hit
        the cache entry of the original call, even when its terms would not
        make the most-common cut.
        """
        values: list[str] = []
        for item in items:
            f = item.features
            values.extend(f.products[:2] + f.customers[:2] + f.entities[:4] + f.tags[:4])
        values.extend(context or [])
        top = [v.lower() for v, _ in Counter(values).most_common(12)]
        key = f"{kind}|" + "|".join(sorted(top))
        if extra:
            key += "|extra:" + "|".join(sorted(e.casefold() for e in extra))
        return f"fp_{kind}_" + short_hash(key or "empty", 16)

    def _title(
        self,
        items: list[EnrichedChunk],
        fallback: str,
        *,
        max_words: int,
    ) -> str:
        values: list[str] = []
        for item in items:
            f = item.features
            values.extend(f.products + f.customers + f.tags)
        if not values:
            return fallback
        title = Counter(values).most_common(1)[0][0]
        words = title.replace("-", " ").split()
        capped = words[:max_words]
        return " ".join(part.capitalize() for part in capped)[:48]

    def _region_summary(self, items: list[EnrichedChunk], name: str) -> str:
        tags: list[str] = []
        for item in items:
            tags.extend(item.features.tags[:3])
        common = [v for v, _ in Counter(tags).most_common(4)]
        if common:
            return f"{name} groups chunks about {', '.join(common)}."
        return f"{name} groups related knowledge chunks."

    def _theme_summary(self, items: list[EnrichedChunk], name: str) -> str:
        subtopics = [item.features.subtopic for item in items if item.features.subtopic]
        common = [v for v, _ in Counter(subtopics).most_common(4)]
        if common:
            return f"{name} covers {', '.join(common)}."
        return f"{name} groups related knowledge themes."

    def _tag_blurb(
        self,
        items: list[EnrichedChunk],
        label: str,
        *,
        region_name: str | None = None,
        region_terms: list[str] | None = None,
    ) -> str:
        tags: list[str] = []
        for item in items:
            tags.extend(item.features.tags[:2])
        common = [v for v, _ in Counter(tags).most_common(3)]
        if region_name and common:
            return f"In {region_name}, covers {', '.join(common)}."
        if region_name and region_terms:
            return f"In {region_name}, connects to {', '.join(region_terms[:3])}."
        if common:
            return f"Covers {', '.join(common)}."
        return f"{label} content cluster."

    # ── Stage 3: compiled notes ────────────────────────────────────
    # Both methods return a paragraph or two synthesizing the member chunks.
    # The base class (local mode) returns an extractive concatenation; the
    # OpenAI namer overrides them with a single LLM call apiece.

    def compile_tag_note(
        self,
        label: str,
        blurb: str | None,
        members: list[EnrichedChunk],
        *,
        region_name: str | None = None,
    ) -> str:
        return _extractive_compile_note(label, blurb, members, max_chars=400)

    def compile_region_note(
        self,
        name: str,
        summary: str | None,
        members: list[EnrichedChunk],
        *,
        child_tag_blurbs: list[str] | None = None,
    ) -> str:
        return _extractive_compile_note(
            name,
            summary,
            members,
            max_chars=600,
            extra_lines=child_tag_blurbs or [],
        )

    def compile_entity_blurb(
        self,
        label: str,
        entity_type: str,
        members: list[EnrichedChunk],
    ) -> str:
        """Per-entity compiled note (Stage 4.5). Local-mode baseline =
        extractive; OpenAI override = LLM synthesis."""
        return _extractive_compile_note(
            f"{label} ({entity_type})",
            None,
            members,
            max_chars=400,
        )


def _extractive_compile_note(
    title: str,
    blurb: str | None,
    members: list[EnrichedChunk],
    *,
    max_chars: int,
    extra_lines: list[str] | None = None,
) -> str:
    """Concat the first chunk summaries until max_chars; use as long-tail
    fallback in OpenAI mode and as the only output in local mode."""
    pieces: list[str] = []
    if blurb:
        pieces.append(blurb.strip())
    for line in extra_lines or []:
        if line and line.strip():
            pieces.append(line.strip())
    seen_summaries: set[str] = set()
    for item in members:
        summary = (item.features.summary or "").strip()
        if not summary or summary in seen_summaries:
            continue
        seen_summaries.add(summary)
        pieces.append(summary[:max_chars])
        joined = " ".join(pieces)
        if len(joined) >= max_chars:
            return joined[:max_chars].rstrip()
    if not pieces:
        return f"{title} content cluster."
    return " ".join(pieces)[:max_chars]
