from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from src.terrain.agents.usage import ledger as _usage
from src.terrain.agents.openai_clients import (
    OpenAIClusterNamer,
    OpenAIEmbeddingClient,
    OpenAIFeatureExtractor,
)
from src.terrain.agents.anthropic_clients import (
    DEFAULT_ANTHROPIC_EXTRACT_MODEL,
    DEFAULT_ANTHROPIC_NAMER_MODEL,
    AnthropicClusterNamer,
    AnthropicFeatureExtractor,
)
from src.terrain.agents.claude_cli import DEFAULT_CLAUDE_MODEL, DEFAULT_CLAUDE_NAMER_MODEL
from src.terrain.agents.claude_clients import ClaudeClusterNamer, ClaudeFeatureExtractor
from src.terrain.preprocessing.chunker import ChunkerRegistry
from src.terrain.preprocessing.extractor import FeatureExtractor
from src.terrain.preprocessing.reader import TerrainReader
from src.terrain.utils.clusterer import (
    MULTI_REGION_SIMILARITY_THRESHOLD,
    TerrainClusterer,
)
from src.terrain.utils.embedder import EmbeddingClient, LocalHashEmbeddingClient
from src.terrain.utils.emitter import KnowledgeMapEmitter
from src.terrain.utils.layout import TerrainLayout
from src.terrain.utils.models import (
    AggregateCounts,
    AttentionSignal,
    Bounds,
    KnowledgeMap,
    KnowledgeMapBuildResult,
    KnowledgeMapNotes,
    ClusterTreeNode,
    CompilerProvenance,
    Deltas,
    Edges,
    EnrichedChunk,
    GraphEdge,
    GraphNode,
    GraphView,
    Highlights,
    Note,
    NoteSource,
    Offset,
    Owner,
    Position,
    RegionEdge,
    RegionWeight,
    SourceDocument,
    Stats,
    SurprisingEdge,
    Tag,
    TagEdge,
    TerrainChunk,
    TreeNode,
    validate_bidirectional,
)
from src.terrain.utils.attention import (
    aggregate_attention,
    attention_score as attention_score_fn,
    calibrate_attention,
    extract_attention_signals,
    signals_cache_lines,
    signals_digest,
)
from src.terrain.utils.canonicalize import fuzzy_canonical_map, normalize
from src.terrain.utils.containers import container_path
from src.terrain.utils.graph_embed import apply_context_embeddings
from src.terrain.utils.namer import ClusterNamer, _extractive_compile_note
from src.terrain.utils.region_merger import RegionMerger
from src.terrain.utils.store import TerrainStore
from src.utils.hashing import sha256_hash, short_hash
from src.config_file import load_config_file

# Eligibility threshold for LLM-synthesized tag compiled_notes. Long-tail
# tags below this rank fall back to an extractive concat (stored on
# compiled_note_extractive, not surfaced in the UI).
COMPILED_NOTE_TOP_N_TAGS = 15
COMPILED_NOTE_MIN_FREQUENCY = 3

# Stage 4.5 — entity promotion thresholds. Mirrors the tag eligibility
# shape: keep entities mentioned in >=3 distinct notes AND in the top-N
# by mention frequency. Long-tail entities below this fall through to an
# extractive blurb (chatbot retrieval-only).
ENTITY_TOP_N = 30
ENTITY_MIN_NOTES = 3
ENTITY_TYPE_TAG_THRESHOLD = 0.30  # share of a tag's notes that must
                                  # mention the entity before we emit a
                                  # belongs_to_theme edge.
ENTITY_COMENTION_THRESHOLD = 0.20  # min jaccard for entity↔entity edge.
SURPRISING_MIN_DEGREE = 3  # both endpoints must have >= this degree before an
                           # edge is eligible as a "surprising connection" —
                           # the novelty ratio otherwise rewards rare-node pairs
                           # (random noise) on small graphs.
LEIDEN_WEIGHT_BUMP = 0.1  # additive nudge to an edge's weight when both
                          # endpoints fall in the same Leiden community. This is
                          # the soft signal by which Leiden influences retrieval
                          # (hop thresholds + context-embedding mixing).


logger = logging.getLogger(__name__)

# Type alias: a progress sink. The compile orchestrator passes one that
# forwards each event onto the SSE bus (via loop.call_soon_threadsafe,
# since build() runs in a worker thread).
ProgressFn = Callable[[dict], None]


class _CompileCancelled(Exception):
    """Raised by build() when ``cancel`` is set between chunks/names.

    Cooperative cancellation only — an in-flight LLM call still finishes.
    """


def _now_ms() -> float:
    return time.time() * 1000.0


# A YYYY-MM-DD anywhere in a note title/filename — how dated Obsidian notes
# are named ("1on1 Nadia - 2026-05-19", "Board Update 2026-05").
# Digit lookarounds keep ID-like tokens ("PROJ-2024-1234") from half-matching.
_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})(?:-(\d{2}))?(?!\d)")


def _coerce_iso_date(value: object) -> str | None:
    """Coerce a frontmatter date value to an ISO-8601 string.

    PyYAML parses ``Date: 2026-06-10`` into a ``date``/``datetime`` object, so
    accept those as well as plain strings. Returns None for anything that
    isn't a usable date so the caller can fall through to the next source.
    """
    from datetime import date as _date

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, _date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _iso_date_in_text(text: str) -> str | None:
    """First YYYY-MM(-DD) found in ``text``, as an ISO date string (defaulting
    a missing day to the 1st). None if no plausible date is present."""
    match = _ISO_DATE_RE.search(text)
    if not match:
        return None
    year, month, day = match.group(1), match.group(2), match.group(3) or "01"
    try:
        if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
            return None
    except ValueError:
        return None
    return f"{year}-{month}-{day}"


def _strip_chatbot_fields(obj: object) -> None:
    """Recursively drop ``embedding``, ``context_embedding``, and
    ``compiled_note`` from a model_dump dict — used so the v3 render-data
    bake doesn't inherit megabyte-scale embedding arrays it never reads."""
    if isinstance(obj, dict):
        for k in ("embedding", "context_embedding", "compiled_note", "compiled_note_extractive"):
            obj.pop(k, None)
        for v in obj.values():
            _strip_chatbot_fields(v)
    elif isinstance(obj, list):
        for item in obj:
            _strip_chatbot_fields(item)


def _compile_cache_key(
    prompt_version: str,
    kind: str,
    node_id: str,
    members: list,
    *,
    extras: list[str] | None = None,
) -> str:
    """Stable hash over the compile inputs. Cache hits when neither the
    prompt nor the member content has changed."""
    member_hashes = sorted(getattr(m.chunk, "content_hash", "") for m in members)
    extras_part = "|".join(extras or [])
    payload = f"{prompt_version}|{kind}|{node_id}|{extras_part}|" + "|".join(member_hashes)
    return sha256_hash(payload)


def _llm_concurrency() -> int:
    """Max concurrent LLM calls. ``TERRAIN_LLM_CONCURRENCY=1`` reproduces the
    old fully-serial behavior (a verification lever)."""
    try:
        return max(1, int(os.getenv("TERRAIN_LLM_CONCURRENCY", "16")))
    except ValueError:
        return 16


def _note_reuse_overlap() -> float:
    """Minimum Jaccard overlap (by member content hash) for a cached compiled
    note to be carried forward onto a near-identical member set instead of
    re-synthesized. ``TERRAIN_NOTE_REUSE_OVERLAP=0`` disables fuzzy reuse."""
    try:
        return min(1.0, max(0.0, float(os.getenv("TERRAIN_NOTE_REUSE_OVERLAP", "0.9"))))
    except ValueError:
        return 0.9


def _note_reuse_max_drift() -> int:
    """How many consecutive compiles a note may be carried forward (fuzzy hit)
    before it is force re-synthesized, bounding staleness."""
    try:
        return max(0, int(os.getenv("TERRAIN_NOTE_REUSE_MAX_DRIFT", "3")))
    except ValueError:
        return 3


def _member_hashes(members: list) -> list[str]:
    return sorted({getattr(m.chunk, "content_hash", "") for m in members} - {""})


def _extract_batch_size() -> int:
    """How many chunks to pack into one feature-extraction call. The big lever
    for compile startup cost: each call carries fixed overhead (a `claude -p`
    subprocess cold-start in claude mode, an HTTP round-trip in openai mode), so
    batching amortizes it across many chunks. ``TERRAIN_EXTRACT_BATCH_SIZE=1``
    reproduces the old one-call-per-chunk behavior."""
    try:
        return max(1, int(os.getenv("TERRAIN_EXTRACT_BATCH_SIZE", "4")))
    except ValueError:
        return 4


# A batch is also capped by total content chars so a few huge chunks don't form
# an oversized, timeout-prone call (co-sized with the claude CLI's scaled timeout).
_EXTRACT_BATCH_MAX_CHARS = 60000
# Inputs per embeddings request. The endpoint accepts a list; this collapses
# ~one HTTP call per chunk into one per batch. Well under the API's input cap.
_EMBED_BATCH_SIZE = 128


# Errors that mean "bad config / no point retrying any chunk" — re-raise to fail
# the whole build instead of skipping items. Transient 429s are absorbed by the
# OpenAI SDK's own retries before they ever surface here. Matched by class name
# so we don't have to import openai at module load (it's a lazy dependency).
# Matched by class name so the provider SDKs stay lazy imports. The auth pair
# covers both the openai and anthropic SDKs (same class names);
# ClaudeCLIUnavailableError is the claude-CLI systemic failure (binary missing,
# login broken, subscription out of quota).
_FATAL_LLM_ERRORS = {
    "AuthenticationError",
    "PermissionDeniedError",
    "ClaudeCLIUnavailableError",
    # openai / anthropic SDK 429 after the SDK's own retries: quota or rate
    # limit. Retrying other chunks in the same run cannot help — stop now,
    # keep what's cached, and let the user resume once the window resets.
    "RateLimitError",
}


def _is_fatal_llm_error(exc: BaseException) -> bool:
    return type(exc).__name__ in _FATAL_LLM_ERRORS


# Human prefix on a run's ``error`` when it stopped on an LLM quota/rate limit.
# The frontend's resume logic keys on this exact prefix (compileResume.ts): a
# resumed run reuses every chunk feature / embedding / name / note already in
# terrain.db, so only the unfinished remainder is re-spent.
RESUMABLE_ERROR_PREFIX = "Usage limit reached"


def compile_error_kind(exc: BaseException) -> str | None:
    """``usage_limit`` / ``auth`` / ``missing_cli`` for classified LLM failures,
    else None. Walks ``__cause__`` so wrapped errors keep their class."""
    seen = 0
    cur: BaseException | None = exc
    while cur is not None and seen < 5:
        name = type(cur).__name__
        if name == "ClaudeCLIUnavailableError":
            return getattr(cur, "kind", None) or "unknown"
        if name == "RateLimitError":
            return "usage_limit"
        if name in ("AuthenticationError", "PermissionDeniedError"):
            return "auth"
        cur = cur.__cause__ or cur.__context__
        seen += 1
    return None


def describe_compile_error(exc: BaseException) -> str:
    """The ``error`` string stored on a failed run and shown in the UI. A quota
    stop is prefixed with :data:`RESUMABLE_ERROR_PREFIX` and told how to resume."""
    base = (str(exc) or type(exc).__name__).strip()
    kind = compile_error_kind(exc)
    if kind == "usage_limit":
        return (
            f"{RESUMABLE_ERROR_PREFIX} — everything analyzed so far is saved; "
            f"resume when your quota resets. ({base[:220]})"
        )
    if kind == "auth":
        return f"AI engine authentication failed — fix the login/API key, then resume. ({base[:220]})"
    if kind == "missing_cli":
        return f"Claude CLI not found — install it or switch the AI engine in Settings. ({base[:220]})"
    return base


def _render_coverage(knowledge_map: "KnowledgeMap", render_data: dict) -> dict:
    """What the v3 bake actually drew vs what the v2 tree contains.

    The bake can legitimately trim territory, but a top-level region with no
    hexes is invisible in the UI (the legend hides "phantom" regions) and a tag
    absent from ``tagIndex`` has no spire to click. Both are counted here so
    they show up in the compile log, the run record, and diagnostics instead
    of being discovered by users.
    """
    regions = render_data.get("regions", []) or []
    hexes = render_data.get("hexes", []) or []

    def top_of(i: int) -> int:
        while regions[i]["parentIdx"] >= 0:
            i = regions[i]["parentIdx"]
        return i

    hex_count: Counter[int] = Counter()
    for i in range(0, len(hexes), 5):
        region_idx = hexes[i + 2]
        if region_idx >= 0:
            hex_count[top_of(region_idx)] += 1

    top_idxs = [i for i, r in enumerate(regions) if r.get("level") == 0]
    regions_missing = [regions[i]["name"] for i in top_idxs if hex_count[i] == 0]

    tree_tag_ids: list[str] = []

    def walk(node: "TreeNode") -> None:
        tree_tag_ids.extend(tag.id for tag in node.tags)
        for child in node.children:
            walk(child)

    for root in knowledge_map.tree:
        walk(root)
    rendered = set(render_data.get("tagIndex", []) or [])
    tags_missing = sorted(set(tree_tag_ids) - rendered)

    return {
        "regions_total": len(top_idxs),
        "regions_rendered": len(top_idxs) - len(regions_missing),
        "regions_missing": regions_missing,
        "tags_total": len(set(tree_tag_ids)),
        "tags_rendered": len(set(tree_tag_ids) & rendered),
        "tags_missing": tags_missing,
        "land_hexes": len(hexes) // 5,
        "hexes_per_region": {regions[i]["name"]: hex_count[i] for i in top_idxs},
    }


def _p_log(progress: "ProgressFn", stage: str, msg: str) -> None:
    """Emit a friendly, product-language log line onto the progress stream."""
    progress({
        "type": "log", "level": "info", "stage": stage, "msg": msg, "ts": _now_ms(),
    })


# Min cosine for a tag/region to list a NON-home top-level region in its
# weighted membership (the popover surface). Deliberately separate from the
# clusterer's MULTI_REGION_SIMILARITY_THRESHOLD (which drives chunk-level
# membership and thus clustering) so tuning popover sensitivity never silently
# changes region shapes. Defaults to the same value.
TAG_REGION_WEIGHT_THRESHOLD = MULTI_REGION_SIMILARITY_THRESHOLD


def _region_weights_from_centroids(
    centroid: "np.ndarray | None",
    top_centroids: "dict[str, np.ndarray]",
    home_top_id: str,
    threshold: float = TAG_REGION_WEIGHT_THRESHOLD,
) -> list[RegionWeight]:
    """Weighted many-to-many region membership for one tag/region.

    The home top-level region is always present at weight 1.0; every OTHER
    top-level region whose centroid cosine ≥ ``threshold`` is included with
    that similarity as its weight. Result is home-first, then strongest-first.
    Centroids must already be L2-normalized (so the dot product is cosine).
    """
    home = RegionWeight(regionId=home_top_id, weight=1.0, isHome=True)
    related: list[RegionWeight] = []
    if centroid is not None:
        for top_id, top_c in top_centroids.items():
            if top_id == home_top_id:
                continue
            sim = float(centroid @ top_c)
            if sim >= threshold:
                related.append(
                    RegionWeight(
                        regionId=top_id,
                        weight=round(min(max(sim, 0.0), 1.0), 3),
                    )
                )
    related.sort(key=lambda w: (-w.weight, w.regionId))
    return [home] + related


_SOURCE_MAP: dict[str, NoteSource] = {
    "obsidian": "obsidian",
    "notion": "notion",
    "confluence": "confluence",
    "jira": "jira",
    "gmail": "gmail",
    "calendar": "calendar",
    "slack": "slack",
}


_PALETTE: list[tuple[str, str]] = [
    ("#3F6DF3", "#7AA2FF"),  # blue
    ("#8B5CF6", "#B79BFF"),  # purple
    ("#14B8A6", "#5EEAD4"),  # teal
    ("#F59E0B", "#FCD34D"),  # amber
    ("#EF4444", "#FCA5A5"),  # red
    ("#10B981", "#6EE7B7"),  # emerald
    ("#EC4899", "#F9A8D4"),  # pink
    ("#6366F1", "#A5B4FC"),  # indigo
]


class TerrainCompiler:
    version = "0.2.0"

    def __init__(
        self,
        data_dir: str | Path = ".mnemify",
        *,
        manifest_path: str | Path | None = None,
        store: TerrainStore | None = None,
        extractor: FeatureExtractor | None = None,
        embedder: EmbeddingClient | None = None,
        namer: ClusterNamer | None = None,
        ai_mode: str = "openai",
        # None means "use the mode's default". openai: gpt-5.6-luna. A concrete
        # OpenAI model string overrides it. (Claude per-step models are set via
        # claude_extract_model / claude_name_model below, not llm_model.)
        llm_model: str | None = None,
        # claude + anthropic modes: per-step model aliases (sonnet/opus/haiku).
        # None falls back to the Sonnet-extract / Opus-name defaults. Independent
        # so the chunk-analysis and region/topic-naming steps can differ.
        claude_extract_model: str | None = None,
        claude_name_model: str | None = None,
        embedding_model: str = "text-embedding-3-large",
        # Max concurrent LLM calls during enrich; None falls back to the
        # TERRAIN_LLM_CONCURRENCY env var (default 16) via _llm_concurrency().
        llm_concurrency: int | None = None,
        # Chunks packed per feature-extraction call; None falls back to the
        # TERRAIN_EXTRACT_BATCH_SIZE env var (default 4) via _extract_batch_size().
        extract_batch_size: int | None = None,
        # Reasoning effort per step ("low"/"medium"/"high"; None = provider
        # default). Applies to every LLM engine: OpenAI ``reasoning.effort``,
        # Anthropic ``output_config.effort``, Claude CLI ``--effort``. Not part
        # of any cache key — changing it never forces re-extraction.
        extract_effort: str | None = None,
        name_effort: str | None = None,
        workspace: str = "Mnemify",
        owner: Owner | None = None,
    ):
        self.data_dir = Path(data_dir)
        self.manifest_path = (
            Path(manifest_path)
            if manifest_path
            else self.data_dir / "harvest-manifest.db"
        )
        self.terrain_path = self.data_dir / "terrain.json"
        self.render_data_path = self.data_dir / "render-data.json"
        self.store = store or TerrainStore(self.data_dir / "terrain.db")
        self.ai_mode = ai_mode
        self.embedding_model = embedding_model
        self._llm_concurrency = llm_concurrency
        self._extract_batch_size = extract_batch_size
        self.extract_effort = extract_effort or None
        self.name_effort = name_effort or None
        if ai_mode == "openai":
            openai_model = llm_model or "gpt-5.6-luna"
            self.extractor = extractor or OpenAIFeatureExtractor(
                model=openai_model, effort=self.extract_effort
            )
            self.embedder = embedder or OpenAIEmbeddingClient(model=embedding_model)
            self.namer = namer or OpenAIClusterNamer(
                self.store, model=openai_model, effort=self.name_effort
            )
        elif ai_mode == "anthropic":
            # Anthropic API (metered, ANTHROPIC_API_KEY) — same prompts as the
            # other LLM modes, Messages-API transport. Shares the per-step
            # opus/sonnet/haiku aliases with claude mode; embeddings stay on
            # OpenAI (no Anthropic embeddings API), so OPENAI_API_KEY is still
            # required.
            extractor_model = claude_extract_model or DEFAULT_ANTHROPIC_EXTRACT_MODEL
            namer_model = claude_name_model or DEFAULT_ANTHROPIC_NAMER_MODEL
            self.extractor = extractor or AnthropicFeatureExtractor(
                model=extractor_model, effort=self.extract_effort
            )
            self.embedder = embedder or OpenAIEmbeddingClient(model=embedding_model)
            self.namer = namer or AnthropicClusterNamer(
                self.store, model=namer_model, effort=self.name_effort
            )
        elif ai_mode == "local":
            self.extractor = extractor or FeatureExtractor()
            self.embedder = embedder or LocalHashEmbeddingClient()
            self.namer = namer or ClusterNamer(self.store)
        elif ai_mode == "claude":
            # Text generation runs on the user's Claude subscription (via the
            # `claude` CLI; see claude_cli/claude_clients). Embeddings have no
            # Claude path, so they stay on OpenAI (pennies) — claude mode still
            # needs OPENAI_API_KEY for the embedder.
            # Per-step model selection (replaces the old single-preset tiering):
            # the high-volume chunk feature-extraction step and the user-facing
            # region/topic-naming step each pick their own model. Defaults
            # reproduce the old "balanced" pair — Sonnet for extraction, Opus for
            # naming — when a step is left unset.
            extractor_model = claude_extract_model or DEFAULT_CLAUDE_MODEL
            namer_model = claude_name_model or DEFAULT_CLAUDE_NAMER_MODEL
            self.extractor = extractor or ClaudeFeatureExtractor(
                model=extractor_model, effort=self.extract_effort
            )
            self.embedder = embedder or OpenAIEmbeddingClient(model=embedding_model)
            self.namer = namer or ClaudeClusterNamer(
                self.store, model=namer_model, effort=self.name_effort
            )
        else:
            raise ValueError("ai_mode must be 'openai', 'anthropic', 'local', or 'claude'")

        # Compiled-note cache version — tag the backend so Claude-, Anthropic-
        # and OpenAI-synthesized notes never collide in the compiled-notes cache.
        from src.terrain.agents.openai_clients import PROMPT_VERSION as _base_prompt_version
        self._compile_prompt_version = (
            f"{_base_prompt_version}|{getattr(self.extractor, 'schema_version', ai_mode)}"
            if ai_mode in ("claude", "anthropic")
            else _base_prompt_version
        )

        self.workspace = workspace
        self.owner = owner or Owner(name="Mnemify User", role="Knowledge Worker")
        self.emitter = KnowledgeMapEmitter()
        # When True, a build ignores the feature/embedding/name caches and
        # recomputes everything from scratch (a true "recompile"). Cache writes
        # still happen, so the refreshed values are saved for the next run. Set
        # per-build by build(fresh=...).
        self._fresh = False

    # ── Public API ─────────────────────────────────────────────────

    def build(
        self,
        source: str | None = None,
        *,
        progress: ProgressFn | None = None,
        cancel: "threading.Event | None" = None,
        fresh: bool = False,
    ) -> KnowledgeMapBuildResult:
        """Compile harvested docs → v2 ``terrain.json`` (+ companion notes,
        + v3 ``render-data.json``).

        ``progress`` (optional) receives a stream of stage events:
        ``{"stage": "load"|"chunk"|"enrich"|"cluster"|"derive"|"validate"|
        "emit"|"render", "done"?, "total"?, "cached"?, "count"?, "ts": ...}``
        (plus ``{"type":"log"|"error", ...}`` lines). ``cancel`` (optional,
        a ``threading.Event``) is checked between chunks/names — cooperative.
        """
        _p: ProgressFn = progress or (lambda _ev: None)
        self._fresh = fresh
        _usage.reset()
        run_id = self.store.start_run(
            {
                "source": source, "ai_mode": self.ai_mode, "fresh": fresh,
                "extract_effort": self.extract_effort, "name_effort": self.name_effort,
            }
        )
        try:
            logger.info("terrain: loading harvested documents")
            documents = TerrainReader(self.manifest_path).load(source=source)
            logger.info("terrain: loaded %s documents", len(documents))
            if not documents:
                # Fail LOUD: completing here would overwrite terrain.json with
                # an empty map. Zero loadable docs means the harvest data is
                # missing or its stored paths don't resolve on this machine —
                # not a valid "empty corpus" compile.
                raise RuntimeError(
                    "no documents could be loaded from the harvest manifest"
                    + (f" (source={source})" if source else "")
                    + " — compile aborted before overwriting the existing map. "
                    "Check that the harvested files under .mnemify/ exist on "
                    "this machine, then re-run the harvest if needed."
                )
            _p({"stage": "load", "count": len(documents), "ts": _now_ms()})
            _sources = sorted({d.source_type for d in documents})
            if documents:
                _p_log(
                    _p, "load",
                    f"Reading {len(documents)} documents"
                    + (f" from {', '.join(_sources)}" if _sources else ""),
                )

            logger.info("terrain: chunking markdown")
            chunks = ChunkerRegistry().chunk(documents)
            logger.info("terrain: created %s chunks", len(chunks))
            # The enrich denominator is known now.
            _p({"stage": "chunk", "total": len(chunks), "done": 0, "ts": _now_ms()})

            self.store.upsert_chunks(chunks)
            chunked_docs = {c.doc_id for c in chunks}
            unchunked = [d for d in documents if d.id not in chunked_docs]
            if unchunked:
                # Near-empty pages (title-only, a lone image) produce no chunk and
                # therefore never appear on the map or in retrieval. Say so.
                _p_log(
                    _p, "chunk",
                    f"{len(unchunked)} of {len(documents)} documents produced no chunks "
                    "(too little text) and will not appear on the map",
                )
            if fresh and source is None:
                # Chunk ids are content-derived; a fresh, all-sources compile is
                # the one point where rows from earlier chunkings/embedding
                # models are provably orphaned (a single-source compile must not
                # touch other sources' rows). Drop them so chunks↔embeddings
                # joins stay clean.
                pruned = self.store.delete_chunks_not_in([c.id for c in chunks])
                if pruned:
                    logger.info("terrain: pruned %s stale chunk rows", pruned)

            # Resolve the product vocabulary before extraction so it's no longer
            # the founder's hardcoded list. config products are authoritative and
            # cache-keyed; derived-from-prior products are best-effort enrichment.
            config_products, all_products = self._resolve_products()
            if hasattr(self.extractor, "products"):
                self.extractor.products = tuple(all_products)
                self.extractor.cache_products = tuple(config_products)
            if config_products or all_products:
                logger.info(
                    "terrain: products — %d configured, %d total (incl. derived)",
                    len(config_products), len(all_products),
                )

            logger.info("terrain: extracting features and embeddings")
            _usage.set_stage("extract")
            enriched = self._enrich(chunks, progress=_p, cancel=cancel)
            logger.info("terrain: enriched %s chunks", len(enriched))

            logger.info("terrain: clustering regions and tags")
            _p({"stage": "cluster", "ts": _now_ms()})
            clusterer = TerrainClusterer()
            container_by_doc = {
                doc.id: path
                for doc in documents
                if (path := container_path(doc))
            }
            used_containers = bool(container_by_doc)
            if used_containers:
                logger.info(
                    "terrain: container-seeded clustering (%s/%s docs foldered)",
                    len(container_by_doc), len(documents),
                )
                cluster_tree = clusterer.cluster_with_containers(
                    enriched, container_by_doc
                )
            else:
                cluster_tree = clusterer.cluster(enriched)
            merger_llm = self.namer if hasattr(self.namer, "_client") else None
            # With a source-native backbone, the merger stays a conservative
            # janitor: nest related folders, never merge a folder away.
            merger_rows: list[dict] = []

            def on_verdict(v) -> None:
                merger_rows.append({
                    "a_id": v.a_id, "b_id": v.b_id, "similarity": v.similarity,
                    "decision": v.decision, "parent": v.parent, "reason": v.reason,
                    "a_label": v.a_label, "b_label": v.b_label,
                })
                _p_log(
                    _p, "cluster",
                    f"Region merger: '{v.a_label[:40]}' ~ '{v.b_label[:40]}' "
                    f"(sim {v.similarity:.2f}) → {v.decision}"
                    + (f": {v.reason[:120]}" if v.reason else ""),
                )

            _usage.set_stage("merge")
            cluster_tree = RegionMerger(
                merger_llm,
                model=getattr(self.namer, "model", None),
            ).merge(
                cluster_tree,
                enriched,
                allow_merge=not used_containers,
                on_verdict=on_verdict,
            )
            if merger_rows:
                self.store.save_merger_verdicts(run_id, merger_rows)
            self._sync_region_assignments(enriched, cluster_tree)
            clusterer.assign_multi_region(enriched, cluster_tree)
            self.store.upsert_chunks([item.chunk for item in enriched])
            self.store.save_assignments(run_id, cluster_tree)
            logger.info("terrain: built %s top-level clusters", len(cluster_tree))
            _p_log(_p, "cluster", f"Grouped into {len(cluster_tree)} regions")

            logger.info("terrain: deriving v2 knowledge-map model")
            _usage.set_stage("name")
            knowledge_map, map_notes = self._derive(
                documents, enriched, cluster_tree, progress=_p, cancel=cancel
            )
            logger.info(
                "terrain: derived %s regions, %s tags, %s notes",
                knowledge_map.stats.regions,
                knowledge_map.stats.tagsTotal,
                knowledge_map.stats.notes,
            )

            logger.info("terrain: compiling per-tag and per-region notes")
            _usage.set_stage("notes")
            self._compile_summaries(knowledge_map, enriched, progress=_p, cancel=cancel)
            _usage.set_stage("other")

            logger.info("terrain: building flat graph view")
            self._build_graph_view(knowledge_map, map_notes, enriched)

            logger.info("terrain: cross-file validation")
            _p({"stage": "validate", "ts": _now_ms()})
            validate_bidirectional(knowledge_map, map_notes)

            # Persist raw graph-node vectors BEFORE emitting the lean artifact:
            # a crash between the two must never leave a vectorless terrain.json
            # without its table (the reverse — table without artifact — is fine).
            if knowledge_map.graph is not None:
                self.store.replace_graph_node_vectors(
                    {
                        n.id: n.embedding
                        for n in knowledge_map.graph.nodes
                        if n.embedding
                    },
                    model=self.embedding_model,
                )

            logger.info("terrain: writing terrain.json + mocknotes.json")
            _p({"stage": "emit", "ts": _now_ms()})
            terrain_path, notes_path = self.emitter.emit(
                knowledge_map, map_notes, self.data_dir
            )

            # v3 hex bake → .mnemify/render-data.json (what the 3D map reads).
            # Failure here is non-fatal: the v2 terrain is still valid; the map
            # just won't render until a successful re-compile.
            _p({"stage": "render", "ts": _now_ms()})
            render_data = None
            render_coverage: dict | None = None
            try:
                render_data = self._emit_render_data(knowledge_map, map_notes)
                _p({"stage": "render", "done": 1, "total": 1, "ts": _now_ms()})
                render_coverage = _render_coverage(knowledge_map, render_data)
                _p_log(
                    _p, "render",
                    "Rendered {regions_rendered}/{regions_total} regions, "
                    "{tags_rendered}/{tags_total} tags, {land_hexes} land hexes".format(
                        **render_coverage
                    ),
                )
                if render_coverage["regions_missing"] or render_coverage["tags_missing"]:
                    _p({
                        "type": "log", "level": "warning", "stage": "render",
                        "msg": (
                            "Render dropped content: "
                            f"regions without hexes={render_coverage['regions_missing']} "
                            f"tags without spires={render_coverage['tags_missing']}"
                        )[:400],
                        "ts": _now_ms(),
                    })
            except Exception as e:  # noqa: BLE001
                logger.exception("terrain: v3 render bake failed (v2 terrain is fine)")
                _p({
                    "type": "error", "level": "error", "stage": "render",
                    "msg": f"render-data bake failed: {e}"[:200], "ts": _now_ms(),
                })

            self._log_build_diagnostics(knowledge_map, enriched, render_data, progress=_p)
            run_counts = knowledge_map.stats.model_dump()
            if render_coverage is not None:
                run_counts["render"] = render_coverage
            run_counts["llm_usage"] = _usage.snapshot()
            _p_log(_p, "emit", _usage.summary_line())
            logger.info("terrain: %s", _usage.summary_line())
            self.store.complete_run(run_id, run_counts)
            logger.info("terrain: build complete")
            return KnowledgeMapBuildResult(
                run_id=run_id,
                terrain_path=str(terrain_path),
                notes_path=str(notes_path),
                render_data_path=str(self.render_data_path),
                stats=knowledge_map.stats,
            )
        except Exception as e:
            self.store.fail_run(
                run_id, describe_compile_error(e), counts={"llm_usage": _usage.snapshot()}
            )
            logger.exception("terrain: build failed")
            raise

    def _sync_region_assignments(
        self,
        enriched: list[EnrichedChunk],
        cluster_tree: list[ClusterTreeNode],
    ) -> None:
        """Keep persisted chunk assignments aligned to final top-level roots."""
        root_ids_by_chunk: dict[str, list[str]] = defaultdict(list)
        for root in cluster_tree:
            for chunk_id in root.chunk_ids:
                root_ids_by_chunk[chunk_id].append(root.id)
        for item in enriched:
            item.chunk.region_assignments = sorted(root_ids_by_chunk.get(item.chunk.id, []))

    def _emit_render_data(
        self,
        knowledge_map: KnowledgeMap,
        map_notes: KnowledgeMapNotes,
    ) -> dict:
        """Bake the v2 KnowledgeMap into the v3 hex render-data and write it
        atomically to ``.mnemify/render-data.json``."""
        from src.terrain.render_v3 import bake_v3

        # The chatbot-only fields (graph view, embeddings, compiled notes)
        # stay in terrain.json. Stripping them here keeps render-data.json
        # lean and the bake function from accidentally inheriting them.
        terrain_dict = knowledge_map.model_dump(
            by_alias=True,
            mode="json",
            exclude={"graph": True},
        )
        _strip_chatbot_fields(terrain_dict)
        notes_dict = map_notes.model_dump(by_alias=True, mode="json")
        render = bake_v3(terrain_dict, notes_dict)
        path = self.render_data_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(render, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
        return render

    def _log_build_diagnostics(
        self,
        knowledge_map: KnowledgeMap,
        enriched: list[EnrichedChunk],
        render_data: dict | None,
        progress: "ProgressFn | None" = None,
    ) -> None:
        nodes: list[TreeNode] = []

        def walk(node: TreeNode) -> None:
            nodes.append(node)
            for child in node.children:
                walk(child)

        for root in knowledge_map.tree:
            walk(root)

        name_counts = Counter(node.name for node in nodes if node.name)
        duplicate_names = {
            name: count
            for name, count in name_counts.items()
            if count > 1
        }

        def node_depth(node: TreeNode) -> int:
            if not node.children:
                return node.level
            return max(node_depth(child) for child in node.children)

        max_depth = max((node_depth(root) for root in knowledge_map.tree), default=0)
        membership_counts = [len(item.chunk.region_assignments) for item in enriched]
        avg_memberships = (
            sum(membership_counts) / len(membership_counts)
            if membership_counts else 0.0
        )
        max_memberships = max(membership_counts, default=0)
        critical_count = sum(1 for node in nodes if node.attentionLevel == "critical")
        critical_rate = critical_count / max(len(nodes), 1)
        rendered_tags = (
            len(render_data.get("tagIndex", []))
            if isinstance(render_data, dict)
            else None
        )

        logger.info(
            "terrain diagnostics: regions=%s nodes=%s max_depth=%s "
            "duplicate_names=%s avg_memberships=%.2f max_memberships=%s "
            "critical_rate=%.0f%% terrain_tags=%s rendered_tags=%s",
            len(knowledge_map.tree),
            len(nodes),
            max_depth,
            len(duplicate_names),
            avg_memberships,
            max_memberships,
            critical_rate * 100,
            knowledge_map.stats.tagsTotal,
            rendered_tags if rendered_tags is not None else "unknown",
        )
        if isinstance(render_data, dict):
            cov = _render_coverage(knowledge_map, render_data)
            logger.info(
                "terrain render coverage: regions=%s/%s tags=%s/%s land_hexes=%s "
                "hexes_per_region=%s",
                cov["regions_rendered"], cov["regions_total"],
                cov["tags_rendered"], cov["tags_total"], cov["land_hexes"],
                cov["hexes_per_region"],
            )
            if cov["regions_missing"] or cov["tags_missing"]:
                logger.warning(
                    "terrain render dropped content: regions_without_hexes=%s "
                    "tags_without_spires=%s",
                    cov["regions_missing"], cov["tags_missing"],
                )

        if duplicate_names and progress is not None:
            progress({
                "type": "log", "level": "warning", "stage": "derive",
                "msg": ("Duplicate region names in the compiled tree: "
                        + ", ".join(f"{n} x{c}" for n, c in sorted(duplicate_names.items())))[:300],
                "ts": _now_ms(),
            })
        if duplicate_names:
            sample = ", ".join(
                f"{name} x{count}"
                for name, count in sorted(
                    duplicate_names.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:5]
            )
            logger.warning("terrain diagnostics: duplicate region names: %s", sample)
        if avg_memberships >= 4.0 or max_memberships >= 10:
            logger.warning(
                "terrain diagnostics: high chunk region memberships "
                "(avg %.2f, max %s)",
                avg_memberships,
                max_memberships,
            )
        if nodes and critical_rate >= 0.8:
            logger.warning(
                "terrain diagnostics: %.0f%% of regions are critical",
                critical_rate * 100,
            )
        if rendered_tags is not None and rendered_tags < knowledge_map.stats.tagsTotal:
            logger.warning(
                "terrain diagnostics: render emitted %s/%s terrain tags",
                rendered_tags,
                knowledge_map.stats.tagsTotal,
            )

    # ── Stage helpers ──────────────────────────────────────────────

    def _enrich(
        self,
        chunks: list[TerrainChunk],
        *,
        progress: ProgressFn | None = None,
        cancel: "threading.Event | None" = None,
    ) -> list[EnrichedChunk]:
        _p: ProgressFn = progress or (lambda _ev: None)
        schema_version = getattr(self.extractor, "schema_version", "v1")
        total = len(chunks)

        # Parallelism is confined to the stateless network calls below. ALL
        # ``self.store`` access stays on this (build) thread — the SQLite
        # connection is a single shared handle, unsafe for concurrent use.
        resolved: dict[int, EnrichedChunk] = {}  # 1-based chunk index → result

        # Enrich is reported as two sub-phases so the bar reflects what the build
        # is actually doing — the extraction phase alone runs many minutes on a
        # fresh corpus, and previously emitted NO progress frame until the first
        # embedding batch landed (freezing the UI at the pre-enrich %):
        #   • "extract" — every chunk's features become known (cache hit or LLM
        #     extraction). total = all chunks.
        #   • "embed"   — the subset of chunks needing a fresh embedding vector
        #     (total known only after extraction; emitted then).
        ex_done = 0
        em_done = 0
        em_total = 0

        def ex_tick(n: int) -> None:
            nonlocal ex_done
            ex_done += n
            _p({
                "stage": "enrich", "phase": "extract",
                "done": ex_done, "total": total, "ts": _now_ms(),
            })
            if ex_done % 25 == 0 or ex_done == total:
                logger.info("terrain: analyzed %s/%s chunks", ex_done, total)
                _p({
                    "type": "log", "level": "info", "stage": "enrich",
                    "msg": f"Analyzed {ex_done} of {total} chunks", "ts": _now_ms(),
                })

        def em_tick(n: int) -> None:
            nonlocal em_done
            em_done += n
            _p({
                "stage": "enrich", "phase": "embed",
                "done": em_done, "total": em_total, "ts": _now_ms(),
            })
            if em_total and (em_done % 50 == 0 or em_done == em_total):
                logger.info("terrain: embedded %s/%s chunks", em_done, em_total)

        # Emit a frame up-front so the UI leaves the pre-enrich % immediately,
        # even before the first chunk resolves.
        _p({"stage": "enrich", "phase": "extract", "done": 0, "total": total, "ts": _now_ms()})

        # ── 1. Serial cache-lookup pass → split hits from misses ──
        # extract_units: feature cache miss → run extract (then embed) once per
        #   unique content hash, fanned out to every index sharing it (matches the
        #   existing content-hash cache semantics).
        # embed_units: feature hit but embedding miss → embed once per unique
        #   embedding hash. Features stay PER-INDEX (two different features can
        #   hash to the same embedding text; only the vector is shared).
        extract_units: dict[str, dict] = {}
        embed_units: dict[str, dict] = {}
        # chunk id → embedding hash, stamped onto the chunks table at the end
        # so /api/ask can join chunk → vector without re-deriving the hash.
        chunk_ehash: dict[str, str] = {}
        for index, chunk in enumerate(chunks, 1):
            if cancel is not None and cancel.is_set():
                raise _CompileCancelled("cancelled")
            feature_key = f"{schema_version}:{chunk.content_hash}"
            features = None if self._fresh else self.store.get_features(feature_key)
            if features is None:
                unit = extract_units.get(feature_key)
                if unit is None:
                    extract_units[feature_key] = {"chunk": chunk, "indices": [index]}
                else:
                    unit["indices"].append(index)
                continue
            embedding_text = self.embedder.embedding_text(features, chunk)
            embedding_hash = self.embedder.hash(embedding_text)
            embedding = None if self._fresh else self.store.get_embedding(embedding_hash)
            if embedding is not None:
                resolved[index] = EnrichedChunk(
                    chunk=chunk, features=features, embedding=embedding
                )
                chunk_ehash[chunk.id] = embedding_hash
                ex_tick(1)
                continue
            unit = embed_units.get(embedding_hash)
            if unit is None:
                embed_units[embedding_hash] = {
                    "embedding_text": embedding_text, "items": [(index, features)]
                }
            else:
                unit["items"].append((index, features))
            # Features already known (cache hit); only the embedding is pending.
            ex_tick(1)

        # ── 2. Parallel network pass (store-free) + 3. serial write-back ──
        # Two sub-phases, each a parallel fan-out with serial (build-thread)
        # write-back: (A) batched feature extraction, then (B) batched embedding.
        # Batching is per-CALL only — every chunk is still extracted as its own
        # independent item with its own features (the batch just amortizes call
        # overhead); chunks never share a summary or get merged. Order-sensitive
        # consumers downstream (HDBSCAN) are unaffected because results are mapped
        # back to each chunk's original index, not the order the model returned.
        failures = 0
        # pending_embeds: embedding_hash → {"text", "fanout": [(indices, features)]}.
        # One embedding per unique text, fanned out to every chunk index sharing it.
        pending_embeds: dict[str, dict] = {}

        def _add_pending(ehash: str, text: str, indices: list[int], features) -> None:
            pe = pending_embeds.get(ehash)
            if pe is None:
                pending_embeds[ehash] = {"text": text, "fanout": [(indices, features)]}
            else:
                pe["fanout"].append((indices, features))

        # Feature-hit / embed-miss units already have their text + hash computed.
        for ehash, unit in embed_units.items():
            for index, feats in unit["items"]:
                _add_pending(ehash, unit["embedding_text"], [index], feats)

        def _bump_failures(n: int, what: str, exc: Exception | None) -> None:
            nonlocal failures
            failures += n
            logger.warning("terrain: enrich %s failed, skipping %s piece(s): %s", what, n, exc)
            _p({
                "type": "log", "level": "error", "stage": "enrich",
                "msg": f"Skipped {n} piece(s) after a hiccup", "ts": _now_ms(),
            })
            # Advance the relevant phase counter so a skipped piece doesn't
            # leave the bar permanently short of its total.
            if what == "extract":
                ex_tick(n)
            else:
                em_tick(n)
            if failures / max(1, total) > 0.25:
                # Fail LOUD — too many pieces failing means the AI engine is
                # broken, and a compile built from the survivors would be junk.
                raise RuntimeError(
                    f"AI chunk analysis failed for {failures}/{total} pieces "
                    f"(last error: {exc}) — compile aborted. Fix the AI engine "
                    "and recompile, or switch the AI engine to Local in "
                    "Settings → AI & Models for a heuristic-only build."
                ) from exc

        # ── 2A. Batched feature extraction ──
        if extract_units:
            # Group cache-miss units into batches bounded by count AND total
            # content chars (a few huge chunks → a smaller batch).
            max_count = self._extract_batch_size or _extract_batch_size()
            batches: list[list[tuple[str, dict]]] = []
            cur: list[tuple[str, dict]] = []
            cur_chars = 0
            for fkey, unit in extract_units.items():
                clen = min(len(unit["chunk"].content), 32000)
                if cur and (len(cur) >= max_count or cur_chars + clen > _EXTRACT_BATCH_MAX_CHARS):
                    batches.append(cur)
                    cur, cur_chars = [], 0
                cur.append((fkey, unit))
                cur_chars += clen
            if cur:
                batches.append(cur)

            def _do_extract_batch(batch: list[tuple[str, dict]]):
                # extract_batch returns a list aligned 1:1 with the input chunks
                # (None for a chunk that failed even at size 1); it handles its
                # own split-on-failure and per-item heuristic fallback.
                return self.extractor.extract_batch([u["chunk"] for _, u in batch])

            executor = ThreadPoolExecutor(max_workers=self._llm_concurrency or _llm_concurrency())
            try:
                fut_meta = {executor.submit(_do_extract_batch, b): b for b in batches}
                for fut in as_completed(fut_meta):
                    if cancel is not None and cancel.is_set():
                        raise _CompileCancelled("cancelled")
                    batch = fut_meta[fut]
                    try:
                        results = fut.result()
                    except _CompileCancelled:
                        raise
                    except Exception as e:  # noqa: BLE001
                        if _is_fatal_llm_error(e):
                            raise
                        _bump_failures(sum(len(u["indices"]) for _, u in batch), "extract", e)
                        continue
                    for (fkey, unit), features in zip(batch, results):
                        if features is None:
                            _bump_failures(len(unit["indices"]), "extract", None)
                            continue
                        self.store.save_features(fkey, features)
                        rep_chunk = unit["chunk"]
                        text = self.embedder.embedding_text(features, rep_chunk)
                        ehash = self.embedder.hash(text)
                        cached = None if self._fresh else self.store.get_embedding(ehash)
                        if cached is not None:
                            for i in unit["indices"]:
                                resolved[i] = EnrichedChunk(
                                    chunk=chunks[i - 1], features=features, embedding=cached
                                )
                                chunk_ehash[chunks[i - 1].id] = ehash
                            ex_tick(len(unit["indices"]))
                        else:
                            _add_pending(ehash, text, unit["indices"], features)
                            # Extraction is done for these indices; embedding is
                            # deferred to phase 2B.
                            ex_tick(len(unit["indices"]))
            finally:
                executor.shutdown(cancel_futures=True)

        # ── 2B. Batched embedding ──
        # Now that extraction is done, the embedding workload is known — switch
        # the bar to the "embed" phase with its real total.
        _usage.set_stage("embed")
        em_total = sum(
            len(idxs) for pe in pending_embeds.values() for idxs, _ in pe["fanout"]
        )
        if em_total:
            _p({"stage": "enrich", "phase": "embed", "done": 0, "total": em_total, "ts": _now_ms()})
        if pending_embeds:
            pending_list = list(pending_embeds.items())
            embed_batches = [
                pending_list[i : i + _EMBED_BATCH_SIZE]
                for i in range(0, len(pending_list), _EMBED_BATCH_SIZE)
            ]

            def _do_embed_batch(batch: list[tuple[str, dict]]):
                texts = [pe["text"] for _, pe in batch]
                try:
                    return self.embedder.embed_batch(texts)
                except Exception as e:  # noqa: BLE001
                    if _is_fatal_llm_error(e):
                        raise
                    # One bad input shouldn't sink the batch — re-embed singly,
                    # marking only the genuine failures (None) for the caller.
                    out: list = []
                    for t in texts:
                        try:
                            out.append(self.embedder.embed(t))
                        except Exception as ie:  # noqa: BLE001
                            if _is_fatal_llm_error(ie):
                                raise
                            out.append(None)
                    return out

            executor = ThreadPoolExecutor(max_workers=self._llm_concurrency or _llm_concurrency())
            try:
                fut_meta = {executor.submit(_do_embed_batch, b): b for b in embed_batches}
                for fut in as_completed(fut_meta):
                    if cancel is not None and cancel.is_set():
                        raise _CompileCancelled("cancelled")
                    batch = fut_meta[fut]
                    try:
                        vectors = fut.result()
                    except _CompileCancelled:
                        raise
                    except Exception as e:  # noqa: BLE001
                        if _is_fatal_llm_error(e):
                            raise
                        _bump_failures(
                            sum(len(idxs) for _, pe in batch for idxs, _ in pe["fanout"]),
                            "embed", e,
                        )
                        continue
                    for (ehash, pe), vector in zip(batch, vectors):
                        if vector is None:
                            _bump_failures(
                                sum(len(idxs) for idxs, _ in pe["fanout"]), "embed", None
                            )
                            continue
                        self.store.save_embedding(ehash, self.embedder.model, vector)
                        for indices, feats in pe["fanout"]:
                            for i in indices:
                                resolved[i] = EnrichedChunk(
                                    chunk=chunks[i - 1], features=feats, embedding=vector
                                )
                                chunk_ehash[chunks[i - 1].id] = ehash
                            em_tick(len(indices))
            finally:
                executor.shutdown(cancel_futures=True)

        self.store.save_chunk_embedding_hashes(chunk_ehash)

        # Assemble in ORIGINAL chunk order (HDBSCAN downstream is order-sensitive);
        # any chunk dropped to a non-fatal failure is simply absent.
        return [resolved[i] for i in range(1, total + 1) if i in resolved]

    # ── Parallel naming helper (shared by the derive passes) ───────

    @staticmethod
    def _norm_name(name: str) -> str:
        return " ".join(name.casefold().split())

    def _resolve_name_collisions(
        self,
        results: dict[str, tuple[str, str]],
        jobs_by_key: dict[str, dict],
        groups: list[tuple[list[str], list[str]]],
        *,
        size_of: Callable[[str], int],
        cancel: "threading.Event | None",
        progress: "ProgressFn",
        max_rounds: int = 2,
    ) -> tuple[dict[str, tuple[str, str]], int]:
        """Make sibling region names unique; returns ``(results, n_renamed)``.

        ``groups`` are ``(sibling result keys, reserved names)`` — reserved
        names (the parent's label) may not be reused by any child. Within a
        group the largest region (``size_of``) keeps a contested name; the
        others are re-named through the normal naming path with
        ``avoid_names`` set to every label taken in the group, for up to
        ``max_rounds``. Anything still colliding gets a deterministic suffix
        from its defining terms so the tree never ships duplicate siblings.

        This is a *labelling* pass only: it never merges or moves regions —
        whether two clusters are the same topic is the region merger's call,
        made on content, not on names.
        """
        results = dict(results)
        n_renamed = 0

        def losers_in(keys: list[str], reserved: list[str]) -> tuple[list[str], set[str]]:
            present = [k for k in keys if k in results]
            reserved_norm = {self._norm_name(n) for n in reserved}
            by_name: dict[str, list[str]] = defaultdict(list)
            for k in present:
                by_name[self._norm_name(results[k][0])].append(k)
            losers: list[str] = []
            for norm, ks in by_name.items():
                ranked = sorted(ks, key=lambda k: (-size_of(k), k))
                if norm in reserved_norm:
                    losers.extend(ranked)
                elif len(ks) > 1:
                    losers.extend(ranked[1:])
            taken = {results[k][0] for k in present} | set(reserved)
            return losers, taken

        for _round in range(max_rounds):
            rename_jobs: list[dict] = []
            for keys, reserved in groups:
                losers, taken = losers_in(keys, reserved)
                for k in losers:
                    job = dict(jobs_by_key[k])
                    job["avoid_names"] = sorted(taken)
                    job["_previous_name"] = results[k][0]
                    rename_jobs.append(job)
            if not rename_jobs:
                return results, n_renamed

            def on_rename(job: dict, name: str, _summary: str) -> None:
                _p_log(
                    progress, "derive",
                    f"Renamed duplicate region '{job['_previous_name']}' → '{name}'",
                )

            renamed = self._name_jobs(rename_jobs, cancel=cancel, on_resolve=on_rename)
            for key, value in renamed.items():
                if value[0] != results[key][0]:
                    n_renamed += 1
                results[key] = value

        # Deterministic fallback for anything still colliding.
        for keys, reserved in groups:
            losers, taken = losers_in(keys, reserved)
            taken_norm = {self._norm_name(t) for t in taken}
            for k in losers:
                name, summary = results[k]
                terms = self._defining_terms(jobs_by_key[k]["items"], limit=6)
                candidates = [
                    f"{name} ({term.title()})" for term in terms
                    if self._norm_name(term) not in self._norm_name(name)
                ]
                candidates.append(f"{name} ({size_of(k)} notes)")
                new_name = next(
                    (c for c in candidates if self._norm_name(c) not in taken_norm),
                    f"{name} #{len(taken_norm) + 1}",
                )
                taken_norm.add(self._norm_name(new_name))
                results[k] = (new_name, summary)
                n_renamed += 1
                progress({
                    "type": "log", "level": "warning", "stage": "derive",
                    "msg": f"Duplicate region name '{name}' persisted after renaming; "
                           f"using '{new_name}'",
                    "ts": _now_ms(),
                })
        return results, n_renamed

    def _name_jobs(
        self,
        jobs: list[dict],
        *,
        cancel: "threading.Event | None",
        on_resolve: Callable[[dict, str, str], None],
    ) -> dict[str, tuple[str, str]]:
        """Resolve a batch of naming jobs → ``{key: (name, summary)}``.

        Each job: ``{key, items, kind: 'theme'|'region'|'tag', fallback?,
        region_name?, region_terms?}``. Mirrors ``_enrich``: serial cache lookup
        → parallel store-free ``_call_*`` → serial ``save_name`` write-back. All
        ``store`` access stays on this build thread. ``on_resolve`` fires serially
        as each name lands (for progress + log events). The local heuristic namer
        has no ``_call_*`` (it's CPU-only), so it runs serially.
        """
        namer = self.namer
        results: dict[str, tuple[str, str]] = {}
        if not jobs:
            return results

        def call_kwargs(job: dict) -> dict:
            kwargs: dict = {}
            if job["kind"] == "tag":
                kwargs["region_name"] = job.get("region_name")
                kwargs["region_terms"] = job.get("region_terms")
            if job.get("avoid_names"):
                # Rename after a sibling label collision (see
                # _resolve_name_collisions): the namer sees the taken names.
                kwargs["avoid_names"] = list(job["avoid_names"])
            return kwargs

        def fingerprint(job: dict) -> str:
            ctx = None
            if job["kind"] == "tag":
                ctx = [job.get("region_name") or "", *(job.get("region_terms") or [])]
            extra = [f"avoid:{n}" for n in job.get("avoid_names") or []] or None
            return namer._fingerprint(job["items"], kind=job["kind"], context=ctx, extra=extra)

        # Local namer: CPU-only wrappers, run serially (no benefit to threads).
        if not hasattr(namer, "_call_theme"):
            for job in jobs:
                if cancel is not None and cancel.is_set():
                    raise _CompileCancelled("cancelled")
                method = getattr(namer, f"name_{job['kind']}")
                name, summary = method(
                    job["items"], job.get("fallback", "General"), **call_kwargs(job)
                )
                results[job["key"]] = (name, summary)
                on_resolve(job, name, summary)
            return results

        # OpenAI mode: serial lookup → parallel network → serial write-back.
        pending: list[tuple[dict, str]] = []
        for job in jobs:
            fp = fingerprint(job)
            cached = None if self._fresh else namer.store.get_name(fp)
            if cached is not None:
                results[job["key"]] = cached
                on_resolve(job, cached[0], cached[1])
            else:
                pending.append((job, fp))

        if pending:
            call = {
                "theme": namer._call_theme,
                "region": namer._call_region,
                "tag": namer._call_tag,
            }
            executor = ThreadPoolExecutor(max_workers=self._llm_concurrency or _llm_concurrency())
            try:
                fut_meta: dict = {}
                for job, fp in pending:
                    fut = executor.submit(
                        call[job["kind"]],
                        job["items"],
                        job.get("fallback", "General"),
                        **call_kwargs(job),
                    )
                    fut_meta[fut] = (job, fp)
                for fut in as_completed(fut_meta):
                    if cancel is not None and cancel.is_set():
                        raise _CompileCancelled("cancelled")
                    job, fp = fut_meta[fut]
                    try:
                        name, summary = fut.result()
                    except _CompileCancelled:
                        raise
                    except Exception as e:  # noqa: BLE001
                        # Fail LOUD — no silent heuristic fallback. A compile
                        # with broken AI naming must abort with a clear error
                        # (surfaced as the run's failure reason), not ship a
                        # map of junk names that looks compiled. Users who
                        # want a no-LLM build pick ai_mode='local' explicitly.
                        raise RuntimeError(
                            f"AI naming failed ({job['kind']}): {e} — compile "
                            "aborted. Fix the AI engine and recompile, or "
                            "switch the AI engine to Local in Settings → AI & "
                            "Models for a heuristic-only build."
                        ) from e
                    namer.store.save_name(fp, name, summary)
                    results[job["key"]] = (name, summary)
                    on_resolve(job, name, summary)
            finally:
                executor.shutdown(cancel_futures=True)
        return results

    def _run_compile_units(
        self,
        units: list,
        work: "Callable[[Any], Any]",
        write_back: "Callable[[Any, Any], None]",
        *,
        cancel: "threading.Event | None",
        parallel: bool,
    ) -> None:
        """Run ``work(unit)`` over cache-miss units, then ``write_back(unit, result)``
        serially on the build thread. Mirrors ``_enrich``/``_name_jobs``: ``work`` is
        store-free (LLM synthesis + embedding) and fans out across a
        ``ThreadPoolExecutor`` in remote mode; ``write_back`` (``store.save_*`` +
        attribute assignment + progress tick) always runs serially on this thread —
        the SQLite store is a single shared handle, unsafe for concurrent use. In
        local mode (``parallel=False``) ``work`` is CPU-only and deterministic, so it
        runs serially too (no thread benefit, and it keeps local output bit-identical).
        Exceptions propagate — a failed note aborts the build, matching the prior
        sequential behavior; ``shutdown(cancel_futures=True)`` cancels the rest.
        """
        if not units:
            return
        if not parallel:
            for unit in units:
                if cancel is not None and cancel.is_set():
                    raise _CompileCancelled("cancelled")
                write_back(unit, work(unit))
            return
        executor = ThreadPoolExecutor(max_workers=self._llm_concurrency or _llm_concurrency())
        try:
            fut_meta = {executor.submit(work, unit): unit for unit in units}
            for fut in as_completed(fut_meta):
                if cancel is not None and cancel.is_set():
                    raise _CompileCancelled("cancelled")
                write_back(fut_meta[fut], fut.result())
        finally:
            executor.shutdown(cancel_futures=True)

    # ── Stage 9 — derive v2 KnowledgeMap + KnowledgeMapNotes ──────────────

    def _derive(
        self,
        documents: list[SourceDocument],
        enriched: list[EnrichedChunk],
        cluster_tree: list[ClusterTreeNode],
        *,
        progress: ProgressFn | None = None,
        cancel: "threading.Event | None" = None,
    ) -> tuple[KnowledgeMap, KnowledgeMapNotes]:
        _p: ProgressFn = progress or (lambda _ev: None)
        return self._derive_tree(
            documents,
            enriched,
            cluster_tree,
            progress=_p,
            cancel=cancel,
        )


    def _derive_tree(
        self,
        documents: list[SourceDocument],
        enriched: list[EnrichedChunk],
        cluster_tree: list[ClusterTreeNode],
        *,
        progress: ProgressFn,
        cancel: "threading.Event | None" = None,
    ) -> tuple[KnowledgeMap, KnowledgeMapNotes]:
        doc_by_id = {d.id: d for d in documents}
        chunks_by_id = {e.chunk.id: e for e in enriched}
        layout = TerrainLayout(self.store)

        all_nodes: list[tuple[ClusterTreeNode, int, str | None, str]] = []
        leaves: list[ClusterTreeNode] = []
        top_by_node: dict[str, str] = {}

        def walk_cluster(
            node: ClusterTreeNode,
            depth: int,
            parent_id: str | None,
            top_id: str | None,
        ) -> None:
            root_id = top_id or node.id
            all_nodes.append((node, depth, parent_id, root_id))
            top_by_node[node.id] = root_id
            if node.children:
                for child in node.children:
                    walk_cluster(child, depth + 1, node.id, root_id)
            else:
                leaves.append(node)

        for root in cluster_tree:
            walk_cluster(root, 0, None, None)

        chunks_by_node: dict[str, list[EnrichedChunk]] = {}
        docs_by_node: dict[str, set[str]] = {}
        for node, _depth, _parent_id, _top_id in all_nodes:
            node_chunks = [
                chunks_by_id[cid]
                for cid in node.chunk_ids
                if cid in chunks_by_id
            ]
            chunks_by_node[node.id] = node_chunks
            docs_by_node[node.id] = {ec.chunk.doc_id for ec in node_chunks}

        signals_by_chunk: dict[str, list[AttentionSignal]] = {}
        for item in enriched:
            doc = doc_by_id.get(item.chunk.doc_id)
            signals_by_chunk[item.chunk.id] = extract_attention_signals(
                item,
                note_id=self._note_id_for(item.chunk.doc_id),
                document=doc,
                # Relative deadline phrases ("Friday", "in 1 week") resolve
                # against the doc's authored date, not harvest mtime.
                anchor_date=self._effective_modified(doc) if doc else None,
            )

        def attention_for_chunks(
            members: list[EnrichedChunk],
            *,
            limit: int = 12,
        ) -> tuple[list[AttentionSignal], float, str]:
            signals: list[AttentionSignal] = []
            for member in members:
                signals.extend(signals_by_chunk.get(member.chunk.id, []))
            return aggregate_attention(
                signals,
                limit=limit,
                context_count=len(members),
            )

        derive_total = max(1, len(all_nodes) + len(leaves))
        derive_done = 0
        progress({"stage": "derive", "done": 0, "total": derive_total, "ts": _now_ms()})

        positions: dict[str, Position] = {}
        radii: dict[str, float] = {}
        positions.update(layout.semantic_positions(cluster_tree, chunks_by_node))

        def radius_for(node: ClusterTreeNode, depth: int) -> float:
            notes = max(len(docs_by_node.get(node.id, set())), 1)
            if depth == 0:
                return max(20.0, min(60.0, 12.0 + 3.5 * math.sqrt(notes)))
            return max(8.0, min(35.0, 7.0 + 2.2 * math.sqrt(notes)))

        def place(node: ClusterTreeNode, depth: int) -> None:
            radii[node.id] = radius_for(node, depth)
            if not node.children:
                return
            child_positions = layout.nested_positions(
                node.id,
                [child.id for child in node.children],
                positions[node.id],
                radii[node.id],
                scale=0.55 if depth == 0 else 0.42,
                child_nodes=node.children,
                chunks_by_node=chunks_by_node,
            )
            positions.update(child_positions)
            for child in node.children:
                place(child, depth + 1)

        for root in cluster_tree:
            place(root, 0)

        tag_to_leaf: dict[str, str] = {}
        tag_to_region: dict[str, str] = {}
        leaf_to_tag: dict[str, str] = {}
        tag_aggregates: dict[str, dict] = {}
        doc_to_tags: dict[str, set[str]] = defaultdict(set)
        # ── Naming (parallelized). Stores carry (name, summary, terms) for
        # themes so build_node need not re-call name_theme just for the summary.
        top_region_context: dict[str, tuple[str, list[str], list[str]]] = {}

        # Round 1 — themes (roots). Must finish before tags: tag prompts +
        # fingerprints depend on the resolved region name/terms.
        theme_jobs = [
            {"key": root.id, "items": chunks_by_node[root.id], "kind": "theme"}
            for root in cluster_tree
            if chunks_by_node.get(root.id)
        ]

        def on_theme(job: dict, name: str, _summary: str) -> None:
            _p_log(progress, "derive", f"Found region: {name}")

        theme_results = self._name_jobs(theme_jobs, cancel=cancel, on_resolve=on_theme)
        # Top-level names are produced by independent LLM calls; nothing above
        # compares them, so two clusters can (and did) both come back as e.g.
        # "Document Intelligence". Rename collisions before anything uses them.
        theme_results, _ = self._resolve_name_collisions(
            theme_results,
            {job["key"]: job for job in theme_jobs},
            groups=[([job["key"] for job in theme_jobs], [])],
            size_of=lambda key: len(docs_by_node.get(key, ())),
            cancel=cancel,
            progress=progress,
        )
        for root in cluster_tree:
            res = theme_results.get(root.id)
            if res is not None:
                name, summary = res
                top_region_context[root.id] = (
                    name, summary, self._defining_terms(chunks_by_node[root.id], limit=5),
                )

        # Round 2 — tags (leaves) + internal-region names, run together in one
        # pool. Tags read the Round-1 region context; region names are independent.
        # NB: a depth>0 leaf is BOTH a tag (named via name_tag) and a region node
        # (named via name_region) — distinct LLM calls. Namespace the job keys so
        # the two results can't clobber each other in the shared results dict.
        leaves_with_chunks = [leaf for leaf in leaves if chunks_by_node.get(leaf.id)]
        tag_jobs: list[dict] = []
        for leaf in leaves_with_chunks:
            top_region_id = top_by_node[leaf.id]
            ctx = top_region_context.get(top_region_id)
            region_name = ctx[0] if ctx else "General"
            region_terms = ctx[2] if ctx else []
            tag_jobs.append({
                "key": f"tag:{leaf.id}", "items": chunks_by_node[leaf.id], "kind": "tag",
                "region_name": region_name, "region_terms": region_terms,
            })
        region_jobs = [
            {"key": f"region:{node.id}", "node_id": node.id,
             "items": chunks_by_node[node.id], "kind": "region", "fallback": "Loose Notes"}
            for node, depth, _parent, _top in all_nodes
            if depth > 0 and chunks_by_node.get(node.id)
        ]

        def on_round2(job: dict, name: str, _summary: str) -> None:
            nonlocal derive_done
            if job["kind"] == "tag":
                derive_done += 1
                progress({"stage": "derive", "done": derive_done, "total": derive_total, "ts": _now_ms()})
                _p_log(progress, "derive", f"Tagged: {name}")

        round2 = self._name_jobs(
            tag_jobs + region_jobs, cancel=cancel, on_resolve=on_round2
        )
        tag_results = {
            leaf.id: round2[f"tag:{leaf.id}"]
            for leaf in leaves_with_chunks
            if f"tag:{leaf.id}" in round2
        }
        region_jobs_by_key = {job["key"]: job for job in region_jobs}
        region_results = {key: round2[key] for key in region_jobs_by_key if key in round2}
        children_by_parent: dict[str | None, list[str]] = defaultdict(list)
        for node, depth, parent_id, _top in all_nodes:
            if depth > 0 and f"region:{node.id}" in region_results:
                children_by_parent[parent_id].append(f"region:{node.id}")
        region_groups: list[tuple[list[str], list[str]]] = []
        for parent_id, keys in children_by_parent.items():
            reserved: list[str] = []
            if parent_id in top_region_context:
                reserved.append(top_region_context[parent_id][0])
            elif f"region:{parent_id}" in region_results:
                reserved.append(region_results[f"region:{parent_id}"][0])
            region_groups.append((keys, reserved))
        region_results, _ = self._resolve_name_collisions(
            region_results,
            region_jobs_by_key,
            groups=region_groups,
            size_of=lambda key: len(docs_by_node.get(key.split(":", 1)[1], ())),
            cancel=cancel,
            progress=progress,
        )
        region_names: dict[str, tuple[str, str]] = {
            job["node_id"]: region_results[job["key"]]
            for job in region_jobs
            if job["key"] in region_results
        }

        # Serial assembly of tag aggregates from the precomputed names.
        # Every leaf job either resolved or aborted the build above, so a
        # missing entry here would be a programming error — index directly.
        for leaf in leaves_with_chunks:
            leaf_chunks = chunks_by_node[leaf.id]
            label, blurb = tag_results[leaf.id]
            tag_id = f"tag.{leaf.id}"
            doc_ids = sorted(docs_by_node[leaf.id])
            signals, attention_score, attention_level = attention_for_chunks(
                leaf_chunks,
                limit=10,
            )
            for doc_id in doc_ids:
                doc_to_tags[doc_id].add(tag_id)
            tag_to_leaf[tag_id] = leaf.id
            tag_to_region[tag_id] = top_by_node[leaf.id]
            leaf_to_tag[leaf.id] = tag_id
            tag_aggregates[tag_id] = {
                "label": label,
                "blurb": blurb,
                "type": self._dominant_tag_type(leaf_chunks),
                "frequency": len(doc_ids),
                "recency": self._max_recency(
                    [doc_by_id[d] for d in doc_ids if d in doc_by_id]
                ),
                "offset": Offset(dx=0.0, dz=0.0),
                "note_ids": [self._note_id_for(d) for d in doc_ids],
                "signals": signals,
                "attention_score": attention_score,
                "attention_level": attention_level,
            }

        cooc: dict[tuple[str, str], int] = defaultdict(int)
        for tag_set in doc_to_tags.values():
            ordered = sorted(tag_set)
            for i, a in enumerate(ordered):
                for b in ordered[i + 1 :]:
                    cooc[(a, b)] += 1

        tag_links_raw: dict[str, set[str]] = defaultdict(set)
        for (a, b), _count in cooc.items():
            tag_links_raw[a].add(b)
            tag_links_raw[b].add(a)
        tag_links = {tid: sorted(links) for tid, links in tag_links_raw.items()}

        raw_scores: dict[str, float] = {}
        for tag_id, agg in tag_aggregates.items():
            degree = len(tag_links.get(tag_id, []))
            raw_scores[tag_id] = agg["frequency"] * agg["recency"] * max(1, degree)
        global_max = max(raw_scores.values(), default=1.0) or 1.0
        elevations = {
            tid: max(1, round(100 * score / global_max))
            for tid, score in raw_scores.items()
        }

        # ── Weighted many-to-many region membership (semantic cosine) ──
        # Recompute centroids against the FINAL post-merge roots here: the
        # pre-merge cosine scores from assign_multi_region are keyed to dead
        # ids (RegionMerger ran after it). Each tag/region gets a weighted list
        # of top-level regions it resembles; its own top region is the home
        # (weight 1.0) and stays the single region used for hex placement.
        def _centroid(node_id: str) -> "np.ndarray | None":
            items = chunks_by_node.get(node_id, [])
            if not items:
                return None
            mat = np.asarray([it.embedding for it in items], dtype=np.float32)
            c = mat.mean(axis=0)
            n = float(np.linalg.norm(c))
            return c / n if n > 1e-8 else None

        top_centroids: dict[str, "np.ndarray"] = {}
        for root in cluster_tree:
            c = _centroid(root.id)
            if c is not None:
                top_centroids[root.id] = c

        def _region_weights_for(node_id: str, home_top_id: str) -> list[RegionWeight]:
            return _region_weights_from_centroids(
                _centroid(node_id), top_centroids, home_top_id
            )

        tags_by_id: dict[str, Tag] = {}
        for tag_id, agg in tag_aggregates.items():
            tags_by_id[tag_id] = Tag(
                id=tag_id,
                label=agg["label"],
                type=agg["type"],
                frequency=agg["frequency"],
                recencyScore=round(float(agg["recency"]), 3),
                degree=len(tag_links.get(tag_id, [])),
                elevation=elevations[tag_id],
                offset=agg["offset"],
                noteIds=agg["note_ids"],
                linkedTagIds=tag_links.get(tag_id, []),
                regionWeights=_region_weights_for(
                    tag_to_leaf[tag_id], tag_to_region[tag_id]
                ),
                blurb=agg["blurb"],
                attentionScore=agg["attention_score"],
                attentionLevel=agg["attention_level"],
                signals=agg["signals"],
            )

        def source_count(node_id: str) -> int:
            return len({ec.chunk.source_type for ec in chunks_by_node.get(node_id, [])})

        def build_node(
            node: ClusterTreeNode,
            depth: int,
            parent_id: str | None,
            palette_index: int,
        ) -> TreeNode | None:
            nonlocal derive_done
            node_chunks = chunks_by_node.get(node.id, [])
            if not node_chunks:
                return None
            child_nodes = [
                child_model
                for child in node.children
                if (
                    child_model := build_node(
                        child, depth + 1, node.id, palette_index
                    )
                ) is not None
            ]
            tag_id = leaf_to_tag.get(node.id)
            node_tags = [tags_by_id[tag_id]] if tag_id in tags_by_id else []
            if not child_nodes and not node_tags:
                return None
            if cancel is not None and cancel.is_set():
                raise _CompileCancelled("cancelled")
            # Names were resolved in parallel above; build_node just reads them.
            if depth == 0:
                ctx = top_region_context.get(node.id)
                if ctx is not None:
                    name, summary = ctx[0], ctx[1]
                else:
                    name, summary = self.namer.name_theme(node_chunks)
            else:
                cached_region = region_names.get(node.id)
                name, summary = cached_region or self.namer.name_region(node_chunks)
            derive_done += 1
            progress({"stage": "derive", "done": derive_done, "total": derive_total, "ts": _now_ms()})
            elevation = max(
                [tag.elevation for tag in node_tags]
                + [child.elevation for child in child_nodes],
                default=1,
            )
            tag_count = len(node_tags) + sum(
                child.aggregateCounts.tags for child in child_nodes
            )
            color, accent = _PALETTE[palette_index % len(_PALETTE)]
            pos = positions[node.id]
            signals, attention_score, attention_level = attention_for_chunks(
                node_chunks,
                limit=12,
            )
            return TreeNode(
                id=node.id,
                name=name,
                level=depth,
                parentId=parent_id,
                position=Position(x=round(pos.x, 3), z=round(pos.z, 3)),
                height=elevation,
                chunk_ids=sorted(node.chunk_ids),
                summary=summary,
                color=color if depth == 0 else None,
                accent=accent if depth == 0 else None,
                center=Position(x=round(pos.x, 3), z=round(pos.z, 3)),
                radius=round(radii[node.id], 3),
                aggregateCounts=AggregateCounts(
                    notes=len(docs_by_node.get(node.id, set())),
                    sources=source_count(node.id),
                    tags=tag_count,
                    subRegions=len(child_nodes),
                ),
                elevation=elevation,
                children=child_nodes,
                tags=node_tags,
                regionWeights=_region_weights_for(node.id, top_by_node[node.id]),
                attentionScore=attention_score,
                attentionLevel=attention_level,
                signals=signals,
            )

        tree: list[TreeNode] = []
        for idx, root in enumerate(cluster_tree):
            built = build_node(root, 0, None, idx)
            if built is not None:
                tree.append(built)

        surviving_regions = [node.id for node in tree]

        # A non-home weight may point to a root that had chunks but produced no
        # surviving TreeNode; drop those so regionWeights only references the
        # final tree (home always survives — its owner is in the tree).
        surviving_top = set(surviving_regions)

        def _prune_weights(node: TreeNode) -> None:
            node.regionWeights = [
                w for w in node.regionWeights if w.regionId in surviving_top
            ]
            for tag in node.tags:
                tag.regionWeights = [
                    w for w in tag.regionWeights if w.regionId in surviving_top
                ]
            for child in node.children:
                _prune_weights(child)

        for root in tree:
            _prune_weights(root)

        # Corpus-relative attention: rescale every region/tag against the
        # corpus so the height/color ramp spreads low→critical instead of
        # saturating at 100. Must run on the FINAL tree (post merge/nest/prune).
        self._calibrate_attention(tree, chunks_by_node, tag_to_leaf)

        region_tokens = {
            rid: self._region_tokens(chunks_by_node[rid])
            for rid in surviving_regions
        }
        name_by_region = {node.id: node.name for node in tree}
        region_edges: list[RegionEdge] = []
        for i, a in enumerate(surviving_regions):
            for b in surviving_regions[i + 1 :]:
                union = region_tokens[a] | region_tokens[b]
                if not union:
                    continue
                inter = region_tokens[a] & region_tokens[b]
                weight = len(inter) / len(union)
                if weight < 0.2:
                    continue
                shared_docs = docs_by_node[a] & docs_by_node[b]
                region_edges.append(
                    RegionEdge.model_validate(
                        {
                            "from": a,
                            "to": b,
                            "type": "co-occurs",
                            "weight": round(weight, 3),
                            "noteCount": len(shared_docs),
                            "rationale": (
                                f"shared {len(inter)} tokens between "
                                f"{name_by_region[a]} and {name_by_region[b]}"
                            ),
                        }
                    )
                )
        region_edges.sort(key=lambda e: e.weight, reverse=True)
        region_edges = region_edges[:20]

        tag_edges: list[TagEdge] = []
        max_cooc = max(cooc.values()) if cooc else 1
        for (a, b), count in cooc.items():
            if a not in tags_by_id or b not in tags_by_id:
                continue
            weight = count / max(1, max_cooc)
            if weight < 0.3:
                continue
            tag_edges.append(
                TagEdge.model_validate(
                    {
                        "from": a,
                        "to": b,
                        "type": "co-occurs",
                        "weight": round(weight, 3),
                        "noteCount": count,
                        "crossRegion": tag_to_region[a] != tag_to_region[b],
                    }
                )
            )
        tag_edges.sort(key=lambda e: e.weight, reverse=True)

        all_tags = list(tags_by_id.values())
        by_degree = sorted(all_tags, key=lambda t: (-t.degree, t.id))
        by_recency = sorted(all_tags, key=lambda t: (-t.recencyScore, t.id))
        highlights = Highlights(
            godTags=[t.id for t in by_degree if t.degree > 0][:10],
            bridgeTags=[
                t.id
                for t in all_tags
                if any(
                    tag_to_region.get(link) != tag_to_region[t.id]
                    for link in t.linkedTagIds
                )
            ],
            trendingTags=[t.id for t in by_recency][:10],
            isolatedTags=[t.id for t in all_tags if t.degree == 0],
        )

        if tree:
            bounds = Bounds(
                minX=min(n.center.x - n.radius for n in tree),
                maxX=max(n.center.x + n.radius for n in tree),
                minZ=min(n.center.z - n.radius for n in tree),
                maxZ=max(n.center.z + n.radius for n in tree),
                maxElevation=100,
            )
        else:
            bounds = Bounds(
                minX=-100, maxX=100, minZ=-100, maxZ=100, maxElevation=100
            )

        surviving_leaves = {node.id for node in leaves if node.id in leaf_to_tag}
        notes_list = self._build_notes(
            documents=documents,
            enriched=enriched,
            doc_to_tags=doc_to_tags,
            tags_by_id=tags_by_id,
            tag_to_leaf=tag_to_leaf,
            surviving_leaves=surviving_leaves,
        )

        def walk_tags(nodes: list[TreeNode]) -> int:
            return sum(len(node.tags) + walk_tags(node.children) for node in nodes)

        def walk_non_roots(nodes: list[TreeNode]) -> int:
            total = 0
            for node in nodes:
                total += sum(1 + walk_non_roots([child]) for child in node.children)
            return total

        stats = Stats(
            regions=len(tree),
            subRegionsTotal=walk_non_roots(tree),
            tagsTotal=walk_tags(tree),
            notes=len(notes_list),
            sources=len({n.source for n in notes_list}),
            edges=len(region_edges) + len(tag_edges),
            deltas=Deltas(),
        )

        knowledge_map = KnowledgeMap(
            version=2,
            schemaName="cortex.brain-map",
            workspace=self.workspace,
            owner=self.owner,
            generatedAt=datetime.now(timezone.utc).isoformat(),
            compiler=CompilerProvenance(
                version=self.version,
                extractor=type(self.extractor).__name__,
                clusterer="TerrainClusterer",
            ),
            bounds=bounds,
            stats=stats,
            highlights=highlights,
            tree=tree,
            edges=Edges(regionEdges=region_edges, tagEdges=tag_edges),
        )
        map_notes = KnowledgeMapNotes(
            version=2,
            generatedAt=knowledge_map.generatedAt,
            notes=notes_list,
        )
        progress({"stage": "derive", "done": derive_done, "total": derive_done, "ts": _now_ms()})
        return knowledge_map, map_notes

    # ── derivation helpers ─────────────────────────────────────────

    def _calibrate_attention(
        self,
        tree: list[TreeNode],
        chunks_by_node: dict[str, list[EnrichedChunk]],
        tag_to_leaf: dict[str, str],
    ) -> None:
        """Overwrite per-region/per-tag ``attentionScore``/``attentionLevel``
        with corpus-relative values. Regions and tags are calibrated as two
        separate populations (different granularities). The raw scores are
        recomputed uncapped from each node's already-trimmed ``signals``, so
        the saturation hidden by the 0–100 clamp is recovered before scaling.
        """
        region_nodes: list[TreeNode] = []
        tag_objs: list[Tag] = []

        def walk(node: TreeNode) -> None:
            region_nodes.append(node)
            tag_objs.extend(node.tags)
            for child in node.children:
                walk(child)

        for root in tree:
            walk(root)

        region_raw = {
            node.id: attention_score_fn(
                node.signals,
                context_count=len(chunks_by_node.get(node.id, [])),
                cap=False,
            )
            for node in region_nodes
        }
        region_cal = calibrate_attention(region_raw)
        for node in region_nodes:
            node.attentionScore, node.attentionLevel = region_cal[node.id]

        tag_raw: dict[str, float] = {}
        for tag in tag_objs:
            leaf_id = tag_to_leaf.get(tag.id)
            context_count = (
                len(chunks_by_node.get(leaf_id, [])) if leaf_id else len(tag.signals)
            )
            tag_raw[tag.id] = attention_score_fn(
                tag.signals, context_count=context_count, cap=False
            )
        tag_cal = calibrate_attention(tag_raw)
        for tag in tag_objs:
            tag.attentionScore, tag.attentionLevel = tag_cal[tag.id]

    def _note_id_for(self, doc_id: str) -> str:
        return f"n-{short_hash(doc_id, 8)}"

    # ── Stage 3.1: product vocabulary resolution ───────────────────

    def _resolve_products(self) -> tuple[list[str], list[str]]:
        """Resolve the product list that drives extraction.

        Returns ``(config_products, all_products)`` where ``all_products`` is
        ``config ∪ derived-from-prior``. Only ``config_products`` are folded
        into the feature cache key (authoritative, user-controlled, stable);
        derived products are best-effort enrichment that influence extraction
        but are deliberately kept out of the cache key so a growing corpus's
        shifting top-N doesn't force a full re-extract on every compile.

        Replaces the old hardcoded ``KNOWN_PRODUCTS`` injection, which biased
        every non-founder corpus toward Docnostic/Sitelens/Book Reading.
        """
        config_products: list[str] = []
        try:
            cfg = load_config_file()
            raw = cfg.get("products")
            if raw is None and isinstance(cfg.get("terrain"), dict):
                raw = cfg["terrain"].get("products")
            if isinstance(raw, list):
                config_products = [str(p).strip() for p in raw if str(p).strip()]
        except Exception:  # noqa: BLE001
            logger.debug("terrain: config product resolution skipped", exc_info=True)

        derived = [] if self._fresh else self._products_from_prior_compile()
        seen = {p.lower() for p in config_products}
        all_products = config_products + [
            p for p in derived if p.lower() not in seen
        ]
        return config_products, all_products

    def _products_from_prior_compile(self, top_n: int = 30) -> list[str]:
        """Derive product names from the previous compile's entity layer
        (``type=entity``, ``entityType=product``), ranked by centrality. Empty
        when no prior ``terrain.json`` exists (the genuinely-fresh-corpus case)."""
        if not self.terrain_path.exists():
            return []
        try:
            data = json.loads(self.terrain_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.debug("terrain: could not read prior terrain.json", exc_info=True)
            return []
        graph = data.get("graph") or {}
        scored = [
            (n.get("label"), float(n.get("centrality") or 0.0))
            for n in graph.get("nodes", [])
            if n.get("type") == "entity"
            and n.get("entityType") == "product"
            and n.get("label")
        ]
        scored.sort(key=lambda kv: -kv[1])
        return [label for label, _ in scored[:top_n]]

    # ── Stage 4: flat graph view ───────────────────────────────────

    def _build_graph_view(
        self,
        knowledge_map: KnowledgeMap,
        map_notes: KnowledgeMapNotes,
        enriched: list[EnrichedChunk],
    ) -> None:
        """Re-index knowledge_map.tree + edges into a flat GraphView for chatbot
        retrieval. Every edge carries provenance + confidence so the chatbot
        can distinguish "explicitly referenced" from "LLM-inferred"."""

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        signal_node_ids: set[str] = set()

        def signal_text(signal: AttentionSignal) -> str:
            owner = f" Owner: {signal.owner}." if signal.owner else ""
            return (
                f"{signal.kind}. {signal.title}. {signal.summary}. "
                f"Status: {signal.status}. Severity: {signal.severity}.{owner}"
            )

        def add_signal_edges(
            owner_id: str,
            signals: list[AttentionSignal],
            *,
            home_region_id: str | None,
        ) -> None:
            for signal in signals:
                if signal.id not in signal_node_ids:
                    text = signal_text(signal)
                    # Embedding precomputed in one (possibly parallel) pass before
                    # this walk — see ``signal_embeddings`` below. Absent ⇒ embed
                    # failed; retrieval falls back to graph hops.
                    embedding = signal_embeddings.get(signal.id)
                    nodes.append(
                        GraphNode(
                            id=signal.id,
                            type="signal",
                            label=signal.title,
                            summary=text,
                            embedding=embedding,
                            homeRegionId=home_region_id,
                            layer=2,
                            centrality=float(signal.severity),
                            recency=1.0 if signal.kind == "recent_change" else 0.0,
                            signalKind=signal.kind,
                            severity=signal.severity,
                            status=signal.status,
                            owner=signal.owner,
                            sourceNoteIds=signal.source_note_ids,
                            sourceChunkIds=signal.source_chunk_ids,
                        )
                    )
                    signal_node_ids.add(signal.id)
                    for note_id in signal.source_note_ids:
                        edges.append(
                            GraphEdge(
                                from_=note_id,
                                to=signal.id,
                                type="has-signal",
                                weight=1.0,
                                provenance="extracted",
                                confidence=1.0,
                            )
                        )
                edges.append(
                    GraphEdge(
                        from_=owner_id,
                        to=signal.id,
                        type="has-signal",
                        weight=max(0.35, min(1.0, signal.severity / 100.0)),
                        provenance="extracted",
                        confidence=1.0,
                    )
                )

        def walk(tree_nodes: list[TreeNode], parent_top_id: str | None) -> None:
            for node in tree_nodes:
                top_id = parent_top_id or node.id
                nodes.append(
                    GraphNode(
                        id=node.id,
                        type="region",
                        label=node.name,
                        summary=node.compiled_note or node.summary,
                        embedding=node.embedding,
                        homeRegionId=top_id,
                        layer=3,
                        centrality=float(
                            len(node.tags) + len(node.children) + node.attentionScore / 25.0
                        ),
                    )
                )
                # A region's own signals live in THAT region — the sub-region
                # when there is one — not its root ancestor. Stamping the root
                # made every "Show on map" under a big parent fly to the same
                # place.
                add_signal_edges(node.id, node.signals, home_region_id=node.id)
                # contains: region → child region
                for child in node.children:
                    edges.append(
                        GraphEdge(
                            from_=node.id,
                            to=child.id,
                            type="contains",
                            weight=1.0,
                            provenance="extracted",
                            confidence=1.0,
                        )
                    )
                # contains: region → tag, plus tag-related edges
                for tag in node.tags:
                    # The containing region is the tag's home: it is the region
                    # whose hexes carry the tag's spire. The isHome weight is a
                    # flat-stage artefact that names the top-level region, and
                    # falling back to `top_id` had the same coarsening effect.
                    home = node.id
                    nodes.append(
                        GraphNode(
                            id=tag.id,
                            type="tag",
                            label=tag.label,
                            summary=(
                                tag.compiled_note
                                or tag.compiled_note_extractive
                                or tag.blurb
                                or ""
                            ),
                            embedding=tag.embedding,
                            homeRegionId=home,
                            layer=2,
                            centrality=float(tag.degree + tag.attentionScore / 25.0),
                            recency=float(tag.recencyScore),
                        )
                    )
                    add_signal_edges(tag.id, tag.signals, home_region_id=home)
                    edges.append(
                        GraphEdge(
                            from_=node.id,
                            to=tag.id,
                            type="contains",
                            weight=1.0,
                            provenance="extracted",
                            confidence=1.0,
                        )
                    )
                    for linked_id in tag.linkedTagIds:
                        edges.append(
                            GraphEdge(
                                from_=tag.id,
                                to=linked_id,
                                type="linked-to",
                                weight=0.5,
                                provenance="inferred",
                                confidence=0.5,
                            )
                        )
                walk(node.children, top_id)

        # Precompute signal embeddings in one pass (parallel in remote mode) so
        # the walk above just looks them up. Embedding lazily inside the walk
        # serialized 30-50 network round-trips. Dedup by signal id; a failed
        # embed yields None (retrieval falls back to graph hops) and never
        # aborts the build — preserving the prior per-signal try/except.
        signal_embeddings: dict[str, "list[float] | None"] = {}
        unique_signals: dict[str, AttentionSignal] = {}

        def collect_signals(tree_nodes: list[TreeNode]) -> None:
            for node in tree_nodes:
                for signal in node.signals:
                    unique_signals.setdefault(signal.id, signal)
                for tag in node.tags:
                    for signal in tag.signals:
                        unique_signals.setdefault(signal.id, signal)
                collect_signals(node.children)

        collect_signals(knowledge_map.tree)

        if unique_signals:
            def _embed_signal(signal: AttentionSignal) -> "list[float] | None":
                try:
                    return self.embedder.embed(signal_text(signal))
                except Exception:  # noqa: BLE001
                    logger.info(
                        "terrain: signal embedding failed for %s; "
                        "retrieval will use graph hops",
                        signal.id,
                        exc_info=True,
                    )
                    return None

            if hasattr(self.namer, "_call_theme"):
                executor = ThreadPoolExecutor(
                    max_workers=self._llm_concurrency or _llm_concurrency()
                )
                try:
                    fut_meta = {
                        executor.submit(_embed_signal, sig): sid
                        for sid, sig in unique_signals.items()
                    }
                    for fut in as_completed(fut_meta):
                        signal_embeddings[fut_meta[fut]] = fut.result()
                finally:
                    executor.shutdown(cancel_futures=True)
            else:
                for sid, sig in unique_signals.items():
                    signal_embeddings[sid] = _embed_signal(sig)

        walk(knowledge_map.tree, None)

        # Note nodes — one per note. Excerpts are short, no embedding for
        # v0.5 (chatbot reaches notes via tag membership, not note-level
        # similarity). sourceChunkIds let /api/ask expand a cited note back
        # to its raw chunk text without re-deriving the doc_id hash.
        chunk_ids_by_note: dict[str, list[str]] = defaultdict(list)
        for ec in enriched:
            chunk_ids_by_note[self._note_id_for(ec.chunk.doc_id)].append(ec.chunk.id)
        for note in map_notes.notes:
            nodes.append(
                GraphNode(
                    id=note.id,
                    type="note",
                    label=note.title,
                    summary=note.excerpt or "",
                    embedding=None,
                    homeRegionId=note.regionId,
                    layer=0,
                    centrality=float(len(note.tagIds)),
                    sourceChunkIds=chunk_ids_by_note.get(note.id, []),
                )
            )
            if note.primaryTagId:
                edges.append(
                    GraphEdge(
                        from_=note.id,
                        to=note.primaryTagId,
                        type="belongs-to",
                        weight=1.0,
                        provenance="extracted",
                        confidence=1.0,
                    )
                )
            for tag_id in note.tagIds:
                if tag_id == note.primaryTagId:
                    continue
                edges.append(
                    GraphEdge(
                        from_=note.id,
                        to=tag_id,
                        type="belongs-to",
                        weight=0.7,
                        provenance="extracted",
                        confidence=0.85,
                    )
                )

        # Region-region from existing regionEdges.
        for re_edge in knowledge_map.edges.regionEdges:
            edges.append(
                GraphEdge(
                    from_=re_edge.from_,
                    to=re_edge.to,
                    type="region-rel",
                    weight=re_edge.weight,
                    provenance="inferred",
                    confidence=max(0.3, min(1.0, re_edge.weight)),
                )
            )

        # Tag-tag co-occurrence from existing tagEdges. These are noteCount-
        # derived, so ``provenance`` is "inferred" — we know the co-occurrence
        # happens in the data, but the *relationship* type is computed.
        for te_edge in knowledge_map.edges.tagEdges:
            edges.append(
                GraphEdge(
                    from_=te_edge.from_,
                    to=te_edge.to,
                    type="co-occurs",
                    weight=te_edge.weight,
                    provenance="inferred",
                    confidence=max(0.3, min(1.0, te_edge.weight)),
                )
            )

        # Stage 4.5 — promote entities (people, products, projects, customers,
        # concepts) to first-class graph nodes alongside tags, adding entity
        # nodes + cross-layer edges (mentions, belongs_to_theme, co-mention).
        # This MUST run before Leiden and the surprising-connections pass so
        # both operate over the full graph; running them on the tag/region-only
        # subgraph excluded entities from communities and under-counted node
        # degrees in the novelty ratio.
        self._promote_entities(knowledge_map, map_notes, enriched, nodes, edges)

        # Leiden communities — soft signal, optional dep. Runs over the full
        # graph (entities included).
        community_by_id = self._run_leiden(nodes, edges)
        if community_by_id:
            for node in nodes:
                node.leidenCommunityId = community_by_id.get(node.id)

        # Surprising connections — novelty = weight / (deg(u) * deg(v)), gated
        # on min endpoint degree so rare-node pairs don't dominate small graphs.
        # Computed on *un-bumped* weights so the Leiden nudge below doesn't
        # inflate the novelty of same-community (i.e. less surprising) edges.
        degree: dict[str, int] = defaultdict(int)
        for e in edges:
            degree[e.from_] += 1
            degree[e.to] += 1
        candidates: list[SurprisingEdge] = []
        for e in edges:
            if e.type not in ("co-occurs", "linked-to", "region-rel"):
                continue
            d_from = max(1, degree.get(e.from_, 1))
            d_to = max(1, degree.get(e.to, 1))
            if min(d_from, d_to) < SURPRISING_MIN_DEGREE:
                continue
            score = e.weight / float(d_from * d_to)
            if score <= 0:
                continue
            candidates.append(
                SurprisingEdge(from_=e.from_, to=e.to, score=round(score, 6))
            )
        candidates.sort(key=lambda s: -s.score)

        # Leiden soft signal: nudge same-community edge weights up so
        # co-community neighbors clear the retrieval hop threshold and pull
        # harder in the context-embedding mix. This is the ONLY path by which
        # Leiden affects ranking. Applied after the surprising pass on purpose.
        if community_by_id:
            for e in edges:
                ca = community_by_id.get(e.from_)
                cb = community_by_id.get(e.to)
                if ca is not None and ca == cb:
                    e.weight = min(1.0, e.weight + LEIDEN_WEIGHT_BUMP)

        # Stage 4.6 — neighborhood-aware context embeddings (mean-of-
        # neighbors baseline). Cheap, no heavy dependencies; upgrades to
        # true GraphSAGE later are non-breaking because the output field
        # (``context_embedding``) is unchanged.
        apply_context_embeddings(nodes, edges)

        knowledge_map.graph = GraphView(
            nodes=nodes,
            edges=edges,
            surprisingConnections=candidates[:20],
        )

    # ── Stage 4.5: entity promotion ────────────────────────────────

    def _promote_entities(
        self,
        knowledge_map: KnowledgeMap,
        map_notes: KnowledgeMapNotes,
        enriched: list[EnrichedChunk],
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Aggregate entity-like tokens across chunks, canonicalize, score by
        mention frequency, synthesize a per-entity compiled note for the
        top-N (LLM in openai mode, extractive in local), embed, and append
        entity nodes + cross-layer edges to the graph view."""
        # Backend-tagged so Claude- and OpenAI-synthesized notes cache separately.
        PROMPT_VERSION = self._compile_prompt_version

        if not enriched:
            return

        # Build doc→note lookup (entities aggregate by note, not chunk).
        note_id_by_doc: dict[str, str] = {
            ec.chunk.doc_id: self._note_id_for(ec.chunk.doc_id) for ec in enriched
        }

        # Raw entity surface keyed by **(label, type)** so the same string
        # appearing across signal sources stays separated when the types
        # disagree: "Stripe" as a customer (from ChunkFeatures.customers)
        # and "Stripe" as a product (from ChunkFeatures.products) become
        # two distinct entity nodes. Collapsing them via a hardcoded
        # priority order destroyed real signal — a user asking "what does
        # the Stripe API do?" would otherwise retrieve customer-relationship
        # notes by accident.
        typed_label_to_notes: dict[tuple[str, str], set[str]] = defaultdict(set)
        typed_label_to_chunks: dict[tuple[str, str], set[str]] = defaultdict(set)

        def _add(label: str, etype: str, ec: EnrichedChunk) -> None:
            cleaned = (label or "").strip()
            if not cleaned or len(cleaned) > 80:
                return
            note_id = note_id_by_doc.get(ec.chunk.doc_id)
            if not note_id:
                return
            typed_label_to_notes[(cleaned, etype)].add(note_id)
            typed_label_to_chunks[(cleaned, etype)].add(ec.chunk.content_hash)

        for ec in enriched:
            f = ec.features
            for ent in f.entities:
                _add(ent, "concept", ec)
            for prod in f.products:
                _add(prod, "product", ec)
            for cust in f.customers:
                _add(cust, "customer", ec)
            for wl in ec.chunk.wikilinks:
                _add(wl, "concept", ec)
            for m in ec.chunk.mentions:
                if m.startswith("@"):
                    _add(m[1:], "person", ec)
                else:
                    _add(m, "project", ec)  # Jira keys, etc.

        if not typed_label_to_notes:
            return

        # Canonicalize per type. Fuzzy-merging "Project Phoenix" with
        # "Phoenix" is correct WITHIN a type; doing it across types would
        # collapse "Stripe (customer)" into "Stripe (product)".
        by_type: dict[str, list[str]] = defaultdict(list)
        for (label, etype) in typed_label_to_notes.keys():
            by_type[etype].append(label)

        canonical_map: dict[tuple[str, str], tuple[str, str]] = {}
        for etype, labels in by_type.items():
            type_specific = fuzzy_canonical_map(labels)
            for raw, canonical in type_specific.items():
                canonical_map[(raw, etype)] = (canonical, etype)

        # Aggregate by canonical (label, type).
        canon_to_notes: dict[tuple[str, str], set[str]] = defaultdict(set)
        canon_to_chunks: dict[tuple[str, str], set[str]] = defaultdict(set)
        for raw_key, canon_key in canonical_map.items():
            canon_to_notes[canon_key].update(typed_label_to_notes[raw_key])
            canon_to_chunks[canon_key].update(typed_label_to_chunks[raw_key])

        # Score + eligibility.
        scored = sorted(
            canon_to_notes.items(),
            key=lambda kv: -len(kv[1]),
        )
        eligible_canonicals: set[tuple[str, str]] = {
            canon_key
            for canon_key, notes in scored[:ENTITY_TOP_N]
            if len(notes) >= ENTITY_MIN_NOTES
        }
        # Keep all (label, type) entries mentioned in >=2 distinct notes;
        # below that the signal is too weak.
        kept = [(ck, n) for ck, n in scored if len(n) >= 2]

        if not kept:
            return

        # Build enriched lookups for compiled-note input.
        enriched_by_chunk_hash: dict[str, list[EnrichedChunk]] = defaultdict(list)
        for ec in enriched:
            enriched_by_chunk_hash[ec.chunk.content_hash].append(ec)

        # Tag note membership (for belongs_to_theme).
        tag_id_to_notes: dict[str, set[str]] = {}

        def collect_tag_notes(tree_nodes: list[TreeNode]) -> None:
            for node in tree_nodes:
                for tag in node.tags:
                    tag_id_to_notes[tag.id] = set(tag.noteIds)
                collect_tag_notes(node.children)

        collect_tag_notes(knowledge_map.tree)

        # Build entity records: serial cache lookup → parallel synth+embed →
        # serial write-back. Entities are mutually independent, so the
        # cache-miss work fans out across threads in remote mode (mirrors the
        # tag/region passes). Local mode runs serially — see ``parallel`` below.
        parallel = hasattr(self.namer, "_call_theme")

        def entity_work(u: dict) -> tuple[str, list[float]]:
            text = (
                self.namer.compile_entity_blurb(u["label"], u["type"], u["members"])
                if u["is_llm_synthesized"]
                else u["text"]
            )
            return text, self.embedder.embed(text)

        def entity_write(u: dict, result: tuple[str, list[float]]) -> None:
            text, embedding = result
            kind = "entity" if u["is_llm_synthesized"] else "entity_extractive"
            self.store.save_compiled_note(
                u["cache_key"], kind, text, embedding, PROMPT_VERSION,
                members=_member_hashes(u["members"]),
            )
            record_slots[u["idx"]] = {
                "id": u["id"], "label": u["label"], "type": u["type"],
                "note_ids": u["note_ids"], "summary": text, "embedding": embedding,
                "is_llm_synthesized": u["is_llm_synthesized"],
            }

        entity_units: list[dict] = []
        record_slots: dict[int, dict] = {}  # kept-index → record, assembled in order below
        for idx, (canon_key, note_set) in enumerate(kept):
            canonical, etype = canon_key
            members = []
            for ch_hash in canon_to_chunks[canon_key]:
                members.extend(enriched_by_chunk_hash.get(ch_hash, []))
            members.sort(key=lambda ec: -(ec.features.confidence or 0))
            if not members:
                continue

            # Entity id incorporates the type so the same canonical label
            # across types yields distinct nodes (e.g., Stripe-customer
            # vs Stripe-product).
            entity_id = f"ent.{short_hash(f'{normalize(canonical) or canonical}|{etype}', 12)}"
            is_llm = canon_key in eligible_canonicals

            cache_key = _compile_cache_key(
                PROMPT_VERSION, "entity", entity_id, members,
                extras=[etype],
            )
            cached = self._lookup_compiled_note(
                cache_key, "entity" if is_llm else "entity_extractive", members,
                fuzzy=is_llm,
            )
            if cached is not None:
                text, embedding = cached
                record_slots[idx] = {
                    "id": entity_id, "label": canonical, "type": etype,
                    "note_ids": note_set, "summary": text, "embedding": embedding,
                    "is_llm_synthesized": is_llm,
                }
                continue

            entity_units.append({
                "idx": idx, "id": entity_id, "label": canonical, "type": etype,
                "note_ids": note_set, "members": members, "cache_key": cache_key,
                "is_llm_synthesized": is_llm,
                # Extractive fallback (no LLM call) is cheap + deterministic —
                # precompute it; only the embedding is deferred to the work pass.
                "text": None if is_llm else _extractive_compile_note(
                    canonical, None, members, max_chars=300
                ),
            })

        self._run_compile_units(
            entity_units, entity_work, entity_write, cancel=None, parallel=parallel
        )

        # Assemble in original ``kept`` order (entity nodes/edges below are
        # keyed by id, but stable order keeps emitted graphs diff-friendly).
        entity_records: list[dict] = [record_slots[i] for i in sorted(record_slots)]

        # Emit entity nodes + cross-layer edges.
        for rec in entity_records:
            nodes.append(
                GraphNode(
                    id=rec["id"],
                    type="entity",
                    label=rec["label"],
                    summary=rec["summary"],
                    embedding=rec["embedding"],
                    homeRegionId=None,
                    layer=1,
                    centrality=float(len(rec["note_ids"])),
                    entityType=rec["type"],
                )
            )
            # note → entity (mentions) — extracted; the note literally
            # contains the label, otherwise the entity wouldn't be aggregated.
            for note_id in rec["note_ids"]:
                edges.append(
                    GraphEdge(
                        from_=note_id,
                        to=rec["id"],
                        type="mentions",
                        weight=1.0,
                        provenance="extracted",
                        confidence=1.0,
                    )
                )
            # entity → tag (belongs_to_theme) — inferred from note overlap.
            for tag_id, tag_notes in tag_id_to_notes.items():
                if not tag_notes:
                    continue
                shared = rec["note_ids"] & tag_notes
                overlap = len(shared) / len(tag_notes)
                if overlap < ENTITY_TYPE_TAG_THRESHOLD:
                    continue
                edges.append(
                    GraphEdge(
                        from_=rec["id"],
                        to=tag_id,
                        type="belongs_to_theme",
                        weight=round(overlap, 3),
                        provenance="inferred",
                        confidence=round(min(1.0, overlap + 0.2), 3),
                    )
                )

        # entity ↔ entity (co-mention) — derived from shared notes.
        for i, a in enumerate(entity_records):
            for b in entity_records[i + 1 :]:
                shared = a["note_ids"] & b["note_ids"]
                if not shared:
                    continue
                denom = min(len(a["note_ids"]), len(b["note_ids"]))
                jacc = len(shared) / max(1, denom)
                if jacc < ENTITY_COMENTION_THRESHOLD:
                    continue
                edges.append(
                    GraphEdge(
                        from_=a["id"],
                        to=b["id"],
                        type="co-mention",
                        weight=round(jacc, 3),
                        provenance="inferred",
                        confidence=round(min(1.0, jacc + 0.2), 3),
                    )
                )

    def _run_leiden(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> dict[str, int]:
        """Compute Leiden community membership. Returns {} if the optional
        ``igraph`` + ``leidenalg`` dependency pair isn't installed — the rest
        of the graph emission proceeds without community ids."""
        try:
            import igraph as ig
            import leidenalg as la
        except ImportError:
            logger.info(
                "terrain: leiden disabled (install igraph + leidenalg for "
                "graph-community ids)"
            )
            return {}

        if not nodes:
            return {}

        id_to_idx = {n.id: i for i, n in enumerate(nodes)}
        edge_pairs: list[tuple[int, int]] = []
        weights: list[float] = []
        for e in edges:
            i = id_to_idx.get(e.from_)
            j = id_to_idx.get(e.to)
            if i is None or j is None or i == j:
                continue
            edge_pairs.append((i, j))
            weights.append(max(1e-3, e.weight * e.confidence))

        if not edge_pairs:
            return {}

        try:
            graph = ig.Graph(n=len(nodes), edges=edge_pairs, directed=False)
            graph.es["weight"] = weights
            partition = la.find_partition(
                graph,
                la.RBConfigurationVertexPartition,
                weights="weight",
                seed=42,
            )
        except Exception:  # noqa: BLE001
            logger.exception("terrain: leiden partition failed; skipping")
            return {}

        return {
            nodes[idx].id: cid
            for cid, cluster in enumerate(partition)
            for idx in cluster
        }

    # ── Stage 3: compiled notes ────────────────────────────────────

    def _compile_summaries(
        self,
        knowledge_map: KnowledgeMap,
        enriched: list[EnrichedChunk],
        *,
        progress: ProgressFn | None = None,
        cancel: "threading.Event | None" = None,
    ) -> None:
        """Populate Tag.compiled_note (top-N LLM-synthesized) or
        Tag.compiled_note_extractive (long-tail), plus TreeNode.compiled_note
        for every region. Embed every compiled note for chatbot retrieval.

        All output is cached by ``hash(prompt_version | kind | node_id |
        sorted(member_content_hashes))``. Cache hits cost zero LLM calls.
        """
        # Backend-tagged so Claude- and OpenAI-synthesized notes cache separately.
        PROMPT_VERSION = self._compile_prompt_version

        _p: ProgressFn = progress or (lambda _ev: None)

        enriched_by_doc: dict[str, list[EnrichedChunk]] = defaultdict(list)
        for ec in enriched:
            enriched_by_doc[ec.chunk.doc_id].append(ec)
        enriched_by_id: dict[str, EnrichedChunk] = {ec.chunk.id: ec for ec in enriched}
        note_to_doc: dict[str, str] = {}
        for ec in enriched:
            note_to_doc[self._note_id_for(ec.chunk.doc_id)] = ec.chunk.doc_id

        # Walk the tree once. Collect all tags (with parent region for
        # framing) and all TreeNodes (in post-order so children compile
        # before their parents — parents reuse child blurbs).
        tags_with_parent: list[tuple[Tag, TreeNode]] = []
        regions_post_order: list[TreeNode] = []
        region_depth: dict[str, int] = {}

        def walk(nodes: list[TreeNode], depth: int = 0) -> None:
            for node in nodes:
                walk(node.children, depth + 1)
                region_depth[node.id] = depth
                for tag in node.tags:
                    tags_with_parent.append((tag, node))
                regions_post_order.append(node)

        walk(knowledge_map.tree)

        # Pick top-N tags by ``elevation`` — the same ranking signal that
        # `_derive_tree` already computed for the hex layout
        # (`frequency × recency × max(1, degree)` normalized to 1–100).
        # Reusing it keeps "top 15 for LLM synthesis" in lockstep with
        # "top 15 by spire height in the UI" — no second formula to keep
        # in sync.
        scored: list[Tag] = sorted(
            [tag for tag, _ in tags_with_parent],
            key=lambda t: (-t.elevation, -t.frequency, t.id),
        )
        eligible_ids: set[str] = {
            tag.id
            for tag in scored[:COMPILED_NOTE_TOP_N_TAGS]
            if tag.frequency >= COMPILED_NOTE_MIN_FREQUENCY
        }

        def tag_members(tag: Tag) -> list[EnrichedChunk]:
            members: list[EnrichedChunk] = []
            for note_id in tag.noteIds:
                doc_id = note_to_doc.get(note_id)
                if doc_id:
                    members.extend(enriched_by_doc.get(doc_id, []))
            members.sort(key=lambda ec: -(ec.features.confidence or 0))
            return members

        def region_members(node: TreeNode) -> list[EnrichedChunk]:
            if node.chunk_ids:
                return [enriched_by_id[cid] for cid in node.chunk_ids if cid in enriched_by_id]
            out: list[EnrichedChunk] = []
            for child in node.children:
                out.extend(region_members(child))
            return out

        total = len(tags_with_parent) + len(regions_post_order)
        done = 0

        def tick(cached: bool) -> None:
            nonlocal done
            done += 1
            _p({
                "stage": "compile_notes", "done": done, "total": total,
                "cached": cached, "ts": _now_ms(),
            })

        def attention_lines(signals: list[AttentionSignal]) -> list[str]:
            return signals_digest(signals, limit=5)

        def attention_key_lines(signals: list[AttentionSignal]) -> list[str]:
            # Severity-free: the deadline boost inside severity is a function
            # of today's date and must not invalidate the note cache.
            return signals_cache_lines(signals, limit=5)

        # Parallel only in remote mode — the local namer has no network calls
        # (CPU-only extractive notes + hash embeddings), so threads buy nothing
        # and serial keeps local-mode output bit-identical. Same signal
        # ``_name_jobs`` uses to decide serial-vs-parallel.
        parallel = hasattr(self.namer, "_call_theme")

        # ── Tag pass (tags are mutually independent → fan out) ─────────
        def tag_work(u: dict) -> tuple[str, list[float]]:
            text = (
                self.namer.compile_tag_note(
                    u["label"], u["blurb"], u["members"], region_name=u["region_name"]
                )
                if u["eligible"]
                else u["text"]
            )
            return text, self.embedder.embed(text)

        def tag_write(u: dict, result: tuple[str, list[float]]) -> None:
            text, embedding = result
            kind = "tag" if u["eligible"] else "tag_extractive"
            self.store.save_compiled_note(
                u["cache_key"], kind, text, embedding, PROMPT_VERSION,
                members=_member_hashes(u["members"]),
            )
            if u["eligible"]:
                u["tag"].compiled_note = text
            else:
                u["tag"].compiled_note_extractive = text
            u["tag"].embedding = embedding
            tick(cached=False)

        tag_units: list[dict] = []
        for tag, parent in tags_with_parent:
            if cancel is not None and cancel.is_set():
                raise _CompileCancelled("cancelled")
            members = tag_members(tag)
            if not members:
                tick(cached=False)
                continue
            signal_lines = attention_lines(tag.signals)
            key_lines = attention_key_lines(tag.signals)
            if tag.id in eligible_ids:
                blurb = tag.blurb
                if signal_lines:
                    blurb = (blurb or "") + "\nAttention signals:\n" + "\n".join(signal_lines)
                cache_key = _compile_cache_key(
                    PROMPT_VERSION, "tag", tag.id, members, extras=key_lines
                )
                cached = self._lookup_compiled_note(cache_key, "tag", members)
                if cached is None:
                    tag_units.append({
                        "tag": tag, "eligible": True, "cache_key": cache_key,
                        "label": tag.label, "blurb": blurb, "members": members,
                        "region_name": parent.name if parent else None,
                    })
                else:
                    tag.compiled_note, tag.embedding = cached
                    tick(cached=True)
            else:
                # Extractive long-tail fallback. Same embedding contract so the
                # chatbot retrieves over every tag in the graph. The extractive
                # text is cheap + deterministic, so compute it now; only the
                # embedding is deferred to the (possibly parallel) work pass.
                text = _extractive_compile_note(
                    tag.label, tag.blurb, members, max_chars=400, extra_lines=signal_lines,
                )
                cache_key = _compile_cache_key(
                    PROMPT_VERSION, "tag_extractive", tag.id, members, extras=key_lines,
                )
                cached = self._lookup_compiled_note(
                    cache_key, "tag_extractive", members, fuzzy=False
                )
                if cached is None:
                    tag_units.append({
                        "tag": tag, "eligible": False, "cache_key": cache_key, "text": text,
                        "members": members,
                    })
                else:
                    _, tag.embedding = cached
                    tag.compiled_note_extractive = text
                    tick(cached=True)

        self._run_compile_units(tag_units, tag_work, tag_write, cancel=cancel, parallel=parallel)

        # ── Region pass ───────────────────────────────────────────────
        # A region note reuses its children's compiled notes (child tags AND
        # child regions) and folds them into its cache key, so children must be
        # done first. Process depth-by-depth, deepest first; regions at the same
        # depth are mutually independent → fan out per level. (Tags above are a
        # hard barrier — region notes read tag.compiled_note.)
        def region_work(u: dict) -> tuple[str, list[float]]:
            text = self.namer.compile_region_note(
                u["name"], u["summary"], u["members"], child_tag_blurbs=u["child_blurbs"],
            )
            return text, self.embedder.embed(text)

        def region_write(u: dict, result: tuple[str, list[float]]) -> None:
            text, embedding = result
            self.store.save_compiled_note(
                u["cache_key"], "region", text, embedding, PROMPT_VERSION,
                members=_member_hashes(u["members"]),
            )
            u["region"].compiled_note = text
            u["region"].embedding = embedding
            tick(cached=False)

        regions_by_depth: dict[int, list[TreeNode]] = defaultdict(list)
        for region in regions_post_order:
            regions_by_depth[region_depth[region.id]].append(region)

        for depth in sorted(regions_by_depth, reverse=True):
            region_units: list[dict] = []
            for region in regions_by_depth[depth]:
                if cancel is not None and cancel.is_set():
                    raise _CompileCancelled("cancelled")
                members = region_members(region)
                if not members:
                    tick(cached=False)
                    continue
                child_blurbs: list[str] = []
                for tag in region.tags:
                    preview = tag.compiled_note or tag.blurb
                    if preview:
                        child_blurbs.append(f"{tag.label}: {preview[:240]}")
                for child in region.children:
                    preview = child.compiled_note or child.summary
                    if preview:
                        child_blurbs.append(f"{child.name}: {preview[:240]}")
                # Prompt gets severity (urgency helps the synthesis); the
                # cache key gets the severity-free lines (see tag pass).
                key_extras = list(child_blurbs)
                for line in attention_lines(region.signals):
                    child_blurbs.append(f"Attention: {line}")
                for line in attention_key_lines(region.signals):
                    key_extras.append(f"Attention: {line}")

                cache_key = _compile_cache_key(
                    PROMPT_VERSION, "region", region.id, members, extras=key_extras,
                )
                cached = self._lookup_compiled_note(cache_key, "region", members)
                if cached is None:
                    region_units.append({
                        "region": region, "cache_key": cache_key, "name": region.name,
                        "summary": region.summary, "members": members,
                        "child_blurbs": child_blurbs,
                    })
                else:
                    region.compiled_note, region.embedding = cached
                    tick(cached=True)

            self._run_compile_units(
                region_units, region_work, region_write, cancel=cancel, parallel=parallel
            )

    def _lookup_compiled_note(
        self,
        cache_key: str,
        kind: str,
        members: list,
        *,
        fuzzy: bool = True,
    ) -> tuple[str, list[float]] | None:
        """Cache lookup for a compiled note.

        Exact key first. On a miss, and only for LLM-synthesized kinds, look
        for a cached note of the same ``kind`` whose synthesized member set
        overlaps the current one by ≥ ``TERRAIN_NOTE_REUSE_OVERLAP``. Cluster
        node ids encode exact membership, so one added/edited chunk used to
        guarantee a miss for its tag *and every ancestor region*; this makes
        the note survive that churn. A fuzzy hit is re-saved under the new
        exact key (origin members carried verbatim, drift+1) so the next
        compile is an exact hit and staleness stays bounded by
        ``TERRAIN_NOTE_REUSE_MAX_DRIFT``.
        """
        if self._fresh:
            return None
        cached = self.store.get_compiled_note(cache_key)
        if cached is not None or not fuzzy:
            return cached
        min_overlap = _note_reuse_overlap()
        max_drift = _note_reuse_max_drift()
        if min_overlap <= 0 or max_drift <= 0:
            return None
        hit = self.store.find_similar_compiled_note(
            kind, self._compile_prompt_version, _member_hashes(members),
            min_overlap=min_overlap, max_drift=max_drift,
        )
        if hit is None:
            return None
        drift = self.store.bump_compiled_note_drift(hit["origin_key"])
        self.store.save_compiled_note(
            cache_key, kind, hit["text"], hit["embedding"], self._compile_prompt_version,
            members=hit["members"], drift=drift, origin_key=hit["origin_key"],
        )
        logger.debug(
            "terrain: reused %s note (overlap %.2f, drift %d)",
            kind, hit["overlap"], drift,
        )
        return hit["text"], hit["embedding"]

    def _coerce_source(self, source_type: str) -> NoteSource:
        mapped = _SOURCE_MAP.get(source_type)
        if mapped:
            return mapped
        logger.warning(
            "terrain: unknown source_type %r, mapping to 'notion'", source_type
        )
        return "notion"

    def _dominant_tag_type(self, ecs: list[EnrichedChunk]) -> str:
        votes = Counter(ec.features.tag_type_hint for ec in ecs)
        return votes.most_common(1)[0][0]

    def _max_recency(self, docs: list[SourceDocument]) -> float:
        # 90-day exponential half-life on each doc's effective authored date.
        scores = [self._recency_for(self._effective_modified(d)) for d in docs]
        return max(scores, default=0.5)

    def _effective_modified(self, doc: SourceDocument) -> str | None:
        """The date that best reflects when a doc was authored.

        For Obsidian, the harvested ``source_modified`` is the filesystem
        mtime — which, for a freshly synced/copied vault, is a bulk timestamp
        identical across notes, so recency carries no signal. Prefer an
        explicit authored date when the source provides one:

        1. a frontmatter date (``Date``/``date``/``created`` …), and
        2. an ISO date embedded in the title/filename (e.g.
           ``1on1 Nadia - 2026-05-19``), which is how dated notes are named
           when there is no frontmatter.

        The harvest mtime stays the fallback for everything else, so
        non-Obsidian sources (which already carry real modified times) are
        unaffected.
        """
        if doc.source_type != "obsidian":
            return doc.source_modified
        metadata = doc.metadata or {}
        for key in ("Date", "date", "created", "Created", "date_created", "updated"):
            iso = _coerce_iso_date(metadata.get(key))
            if iso:
                return iso
        title_date = _iso_date_in_text(doc.title or "")
        if title_date:
            return title_date
        return doc.source_modified

    def _recency_for(self, source_modified: str | None) -> float:
        if not source_modified:
            return 0.5
        try:
            # ISO 8601 with possible 'Z'.
            raw = source_modified.replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return 0.5
        delta_days = max(
            0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
        )
        decay = math.exp(-math.log(2.0) * delta_days / 90.0)
        return max(0.0, min(1.0, decay))

    def _region_tokens(self, ecs: list[EnrichedChunk]) -> set[str]:
        tokens: set[str] = set()
        for ec in ecs:
            f = ec.features
            tokens.update(t.lower() for t in f.tags)
            tokens.update(e.lower() for e in f.entities)
            tokens.update(c.lower() for c in f.customers)
            tokens.update(p.lower() for p in f.products)
        return tokens

    def _defining_terms(self, ecs: list[EnrichedChunk], *, limit: int) -> list[str]:
        terms: list[str] = []
        for ec in ecs:
            f = ec.features
            terms.extend(f.products[:2])
            terms.extend(f.customers[:2])
            terms.extend(f.entities[:4])
            terms.extend(f.tags[:4])
        seen: set[str] = set()
        out: list[str] = []
        for term, _count in Counter(t for t in terms if t).most_common(limit * 3):
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(term)
            if len(out) >= limit:
                break
        return out

    def _build_notes(
        self,
        *,
        documents: list[SourceDocument],
        enriched: list[EnrichedChunk],
        doc_to_tags: dict[str, set[str]],
        tags_by_id: dict[str, Tag],
        tag_to_leaf: dict[str, str],
        surviving_leaves: set[str],
    ) -> list[Note]:
        """One ``Note`` per doc whose chunks land in a surviving leaf node."""
        doc_by_id = {d.id: d for d in documents}
        chunks_by_doc: dict[str, list[EnrichedChunk]] = defaultdict(list)
        for ec in enriched:
            chunks_by_doc[ec.chunk.doc_id].append(ec)

        notes: list[Note] = []
        for did in sorted(doc_to_tags.keys()):
            doc = doc_by_id.get(did)
            if doc is None:
                continue
            tag_ids = [
                tid for tid in doc_to_tags[did]
                if tid in tags_by_id
                and tag_to_leaf.get(tid) in surviving_leaves
            ]
            if not tag_ids:
                continue
            tag_objs = [tags_by_id[tid] for tid in tag_ids]
            tag_objs.sort(
                key=lambda t: (-t.frequency, -t.elevation, t.id)
            )
            primary = tag_objs[0]
            primary_leaf = tag_to_leaf[primary.id]
            note_chunks = chunks_by_doc.get(did, [])
            first_summary = (
                note_chunks[0].features.summary if note_chunks else ""
            )
            excerpt = self._truncate(first_summary or doc.title, 160)
            word_count = len(doc.content.split())
            # Each harvester stores the author under its own key: GitHub
            # "author", Confluence "author_name" (page creator), Notion
            # "created_by", Jira "reporter_name"/"assignee_name".
            # "last_modified_by" is the last editor (Confluence version.by /
            # Notion last_edited_by) — a fallback when the creator is absent.
            author = (
                doc.metadata.get("author")
                or doc.metadata.get("author_name")
                or doc.metadata.get("created_by")
                or doc.metadata.get("last_modified_by")
                or doc.metadata.get("reporter_name")
                or doc.metadata.get("assignee_name")
                or doc.metadata.get("reporter")
                or doc.metadata.get("assignee")
                or "Unknown"
            )
            # Where inside the source the doc lives — Confluence space key,
            # Jira project key. Surfaced on note cards next to the source.
            source_detail = (
                doc.metadata.get("space_key")
                or doc.metadata.get("project_key")
                or ""
            )
            created = (
                doc.metadata.get("created")
                or doc.metadata.get("createdAt")
                or doc.source_modified
                or ""
            )
            updated = doc.source_modified or created or ""
            last_modified_by = doc.metadata.get("last_modified_by")
            notes.append(
                Note(
                    id=self._note_id_for(did),
                    title=doc.title,
                    source=self._coerce_source(doc.source_type),
                    sourceUrl=doc.source_url or "",
                    author=str(author),
                    lastModifiedBy=(
                        str(last_modified_by)
                        if last_modified_by and str(last_modified_by) != str(author)
                        else None
                    ),
                    sourceDetail=str(source_detail),
                    createdAt=str(created),
                    updatedAt=str(updated),
                    regionId=primary_leaf,
                    primaryTagId=primary.id,
                    tagIds=[t.id for t in tag_objs],
                    excerpt=excerpt,
                    wordCount=word_count,
                )
            )
        return notes

    def _truncate(self, text: str, max_chars: int) -> str:
        text = (text or "").strip()
        if len(text) <= max_chars:
            return text
        cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(".,;:!?")
        return cut + "…"
