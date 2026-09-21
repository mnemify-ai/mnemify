from __future__ import annotations

import logging
import os
import threading
import time
from typing import Literal

from pydantic import BaseModel, Field

from src.terrain.preprocessing.extractor import (
    KNOWN_PRODUCTS,
    SCHEMA_VERSION,
    FeatureExtractor,
    heuristic_tag_type,
    products_schema_suffix,
)
# pyrefly: ignore [missing-import]
from src.terrain.utils.embedder import EmbeddingClient
from src.terrain.utils.models import (
    ChunkFeatures,
    ChunkSignalDraft,
    ChunkSignalKind,
    TagType,
    TerrainChunk,
)
from src.terrain.agents.usage import effort_for, ledger
from src.terrain.utils.namer import ClusterNamer

logger = logging.getLogger(__name__)


# Bump to invalidate all compiled-note caches in one go when prompt wording
# or input structure changes meaningfully.
PROMPT_VERSION = "v1.compiled-notes"


class ClusterName(BaseModel):
    name: str = Field(description="Specific 2-4 word title case name.")
    summary: str = Field(description="One sentence describing what unites the cluster.")


class TagName(BaseModel):
    label: str = Field(description="Specific 1-2 word title case tag label.")
    blurb: str = Field(description="One short phrase describing what this tag covers.")


class CompiledNote(BaseModel):
    text: str = Field(
        description=(
            "A 2-3 paragraph synthesis written for an AI assistant to retrieve "
            "as grounded context. Coherent, specific, no hedging, no bullet "
            "lists. Surfaces concrete facts, decisions, and open questions."
        )
    )


class OpenAISignal(BaseModel):
    kind: ChunkSignalKind = Field(
        description=(
            "One of: todo (an action item / next step), risk (a blocker, "
            "concern, or something that could go wrong), decision (a choice "
            "that was made or agreed), open_question (something unresolved "
            "that needs an answer), owner (a person assigned to something "
            "with no other signal type fitting better)."
        )
    )
    title: str = Field(
        description="Short (<15 word) plain-text label for the signal, grounded in the source line."
    )
    summary: str = Field(description="1-2 sentence grounded summary, close to the source wording.")
    severity: int = Field(
        description=(
            "0-100 urgency/importance. Higher for customer-facing, contractual, "
            "or deadline-bound items; lower for routine or low-stakes items."
        )
    )
    status: Literal["open", "resolved"] = Field(
        description="'resolved' only if the text explicitly says it's done/fixed/shipped/approved; otherwise 'open'."
    )
    owner: str | None = Field(
        default=None, description="Person's name if explicitly assigned, else null."
    )
    due_text: str | None = Field(
        default=None,
        description=(
            "The deadline phrase VERBATIM from the text ('by end of April', "
            "'in 1 week', 'due Friday', '2026-05-01'), if the signal has one; "
            "else null. Copy the source wording exactly — do not rephrase."
        ),
    )
    due_date: str | None = Field(
        default=None,
        description=(
            "ISO YYYY-MM-DD, ONLY if an absolute calendar date appears "
            "literally in the text. NEVER resolve relative phrases like "
            "'Friday', 'next week', or 'in 3 days' yourself — leave this null "
            "and let due_text carry them; they are resolved later against the "
            "document's date."
        ),
    )


class OpenAIChunkFeatures(BaseModel):
    summary: str = Field(description="3-5 sentence concise summary.")
    products: list[str] = Field(
        description="Known products that clearly apply (from the provided list)."
    )
    customers: list[str] = Field(
        description="Customer, account, or person names mentioned."
    )
    entities: list[str] = Field(
        description="People, systems, technologies, or organizations mentioned."
    )
    tags: list[str] = Field(description="3-7 topical keywords.")
    tag_type_hint: Literal[
        "concept", "technology", "person", "product", "event", "metric", "place"
    ] = Field(
        description=(
            "What kind of entity this content is primarily about. "
            "Pick ONE of: concept (idea/framework/topic), technology (system/tool), "
            "person (individual/customer/team), product (named product/service), "
            "event (meeting/launch/incident), metric (KPI/measurement), "
            "place (location/region)."
        )
    )
    theme: str = Field(
        description=(
            "The broadest knowledge category this chunk belongs to — the "
            "level-0 region in a hierarchical knowledge map. 1-3 words, "
            "title case. Pick a label that would naturally group MANY "
            "related chunks together (10-50 chunks typical). Examples: "
            "'Machine Learning', 'CAD Design', 'AI Agents', 'Databases', "
            "'Product Strategy', 'Customer Research'. STAY CONSISTENT — if "
            "you've previously called something 'Machine Learning', do not "
            "switch to 'ML' or 'Artificial Intelligence' for similar chunks. "
            "Prefer broader categories over narrow ones. If genuinely "
            "uncategorizable, return 'General'."
        )
    )
    subtopic: str = Field(
        description=(
            "One level narrower than `theme`, used only as a naming hint "
            "inside recursive clusters. 1-4 words, title case. Should group a "
            "small handful of related tags (1-10 chunks typical). Examples "
            "within 'Machine Learning': 'Hyperparameter Tuning', 'Model "
            "Evaluation', 'Data Preprocessing'. Within 'CAD Design': "
            "'Architectural Drawings', 'Mechanical Assemblies', 'Door "
            "Specifications'. Again STAY CONSISTENT across chunks. If the "
            "chunk is too generic to refine, repeat the theme value here."
        )
    )
    confidence: float = Field(description="Extraction confidence from 0.0 to 1.0.")
    signals: list[OpenAISignal] = Field(
        default_factory=list,
        description=(
            "At most 5 concrete operational signals (todos, risks, decisions, "
            "open questions, owners) genuinely and explicitly present in the "
            "text — skip vague or speculative lines. Only extract a signal if "
            "the text truly expresses it: do NOT extract a risk/blocker from a "
            "sentence that explicitly says something is NOT a problem, is "
            "resolved, is fine, or is under control — that is the opposite of "
            "a risk. Return an empty list if nothing concrete applies."
        ),
    )


class OpenAIChunkFeaturesItem(OpenAIChunkFeatures):
    """One chunk's features inside a batched extraction. Carries the integer
    ``id`` of the chunk it describes so results are mapped back by id, never by
    position — a model that drops or reorders items must not silently shift one
    chunk's features onto another."""

    id: int = Field(
        description="Echo back the integer id from the '=== CHUNK id=N ===' header this describes."
    )


class OpenAIChunkFeaturesBatch(BaseModel):
    items: list[OpenAIChunkFeaturesItem] = Field(
        description="Exactly one object per input chunk, each echoing its id."
    )


# ── Client mixin ───────────────────────────────────────────────────


class OpenAIClientMixin:
    # One cached client per owner (extractor / embedder / namer). The SDK client
    # is thread-safe and pools connections, so reusing it across the enrich/derive
    # thread pools is both correct and a latency win over constructing one per
    # call. The lock guards the first-call race when N pool threads hit a cold
    # client simultaneously.
    _openai = None
    _client_lock = threading.Lock()
    # User-facing effort level ("low"/"medium"/"high", None = provider default).
    # Set by the compiler from settings; travels to the provider as
    # ``reasoning={"effort": ...}`` (the OpenAI spelling — the claude/anthropic
    # shims translate that one kwarg to their own parameter).
    effort: str | None = None

    def _llm_kwargs(self) -> dict:
        e = effort_for("openai", self.effort)
        return {"reasoning": {"effort": e}} if e else {}

    def _responses_parse(self, *, input, text_format):  # noqa: A002 (mirror OpenAI kw)
        """``responses.parse`` with the owner's model + effort, recording token
        usage in the compile ledger. Shims (claude / anthropic) return no
        ``usage`` and record their own."""
        started = time.monotonic()
        response = self._client().responses.parse(
            model=self.model, input=input, text_format=text_format, **self._llm_kwargs()
        )
        ledger.record_openai(
            getattr(response, "usage", None), model=self.model,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return response

    def _client(self):
        if self._openai is not None:
            return self._openai
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for terrain OpenAI mode.")
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "Install backend dependencies to use terrain OpenAI mode."
            ) from e

        with self._client_lock:
            if self._openai is None:
                self._openai = OpenAI()
        return self._openai


# ── Feature extractor ──────────────────────────────────────────────


_VALID_TAG_TYPES: set[str] = {
    "concept", "technology", "person", "product", "event", "metric", "place"
}

# Config errors that mean "no point retrying" — must propagate out of the batch
# bisect to abort the build rather than be swallowed into per-chunk skips. Matched
# by class name so openai stays a lazy import (mirrors compiler._FATAL_LLM_ERRORS).
# AuthenticationError/PermissionDeniedError cover both the openai and anthropic
# SDKs (same class names); ClaudeCLIUnavailableError is the claude-CLI analogue.
_FATAL_EXTRACT_ERRORS = {
    "AuthenticationError",
    "PermissionDeniedError",
    "ClaudeCLIUnavailableError",
}

def _describe_llm_error(exc: BaseException) -> str:
    """``str(exc)`` plus the wrapped root cause, when there is one.

    The SDKs wrap *any* failure inside the transport in
    ``APIConnectionError("Connection error.")`` — including pure Python bugs
    such as a codec ``TypeError`` — so the top-level message alone can send
    you chasing the network. Walks ``__cause__``/``__context__`` (capped, like
    ``compiler.compile_error_kind``) and appends the innermost exception.
    """
    root: BaseException = exc
    seen = 0
    while seen < 5:
        nxt = root.__cause__ or root.__context__
        if nxt is None or nxt is root:
            break
        root = nxt
        seen += 1
    if root is exc:
        return str(exc)
    return f"{exc} [caused by {type(root).__name__}: {root}]"


_SYSTEM_EXTRACT = (
    "Extract semantic features from a knowledge-management chunk for use in a "
    "hierarchical knowledge map. Return concise fields. Do not invent products, "
    "customers, or entities. Pick `tag_type_hint` from the seven allowed values. "
    "For `theme` (level-0) and `subtopic` (level-1), be CONSISTENT across chunks "
    "— many chunks should share the same theme. Prefer broad, stable category "
    "names (e.g. 'Machine Learning', 'CAD Design') for theme, and more specific "
    "names for subtopic. The final tags are the narrowest leaves of the hierarchy. "
    "Also extract `signals` per the field's own instructions — be conservative "
    "and negation-aware. When a signal states a deadline ('by Friday', 'end of "
    "April', 'in 1 week'), copy the phrase verbatim into `due_text`; set "
    "`due_date` only for literal absolute dates, never by resolving relative "
    "phrases."
)

_BATCH_SUFFIX = (
    "\n\nYou will receive MULTIPLE chunks, each delimited by a header line "
    "'=== CHUNK id=N ==='. Extract features for EACH chunk INDEPENDENTLY and "
    "return one object per chunk in `items`, echoing that chunk's integer `id`. "
    "Do not merge, skip, reorder, or invent chunks — return exactly one item per "
    "input chunk."
)


_EMPTY_CONTENT_EXTRACTOR = FeatureExtractor()


class OpenAIFeatureExtractor(OpenAIClientMixin):
    # Why the most recent chunk came back as ``None`` from ``extract_batch``.
    # ``extract_batch`` swallows per-chunk failures by contract (one bad piece
    # must not sink the batch), so the compiler reads this to say *what*
    # failed in its "compile aborted" message instead of "last error: None".
    # Last-writer-wins across worker threads is fine — any recent cause beats none.
    last_skip_reason: str | None = None

    def __init__(
        self, model: str = "gpt-5.6-luna", products=KNOWN_PRODUCTS, *,
        cache_products=(), effort: str | None = None,
    ):
        self.model = model
        self.effort = effort
        # ``products`` = all products surfaced in the prompt (config ∪ derived).
        # ``cache_products`` = config-declared only; feeds ``schema_version``.
        self.products = tuple(products)
        self.cache_products = tuple(cache_products)

    @property
    def schema_version(self) -> str:
        # Backend + model tag, like the Claude/Anthropic extractors: features
        # extracted by one model (or by the local heuristics) must never be
        # served as another's from the per-chunk cache.
        return f"openai-{self.model}:{SCHEMA_VERSION}{products_schema_suffix(self.cache_products)}"

    def extract(self, chunk: TerrainChunk) -> ChunkFeatures:
        response = self._responses_parse(
            input=[
                {"role": "system", "content": _SYSTEM_EXTRACT},
                {"role": "user", "content": self._prompt(chunk)},
            ],
            text_format=OpenAIChunkFeatures,
        )
        return self._to_features(response.output_parsed)

    def extract_batch(self, chunks: list[TerrainChunk]) -> list[ChunkFeatures | None]:
        """Extract features for many chunks, routing empty-shell chunks (a
        Notion database row, a link-only block — just title/metadata, no
        body) to the deterministic local heuristic instead of the LLM.

        There is nothing for the LLM to extract from truly empty content, and
        asking it to anyway just invites a conversational refusal (Claude) or
        a degenerate structured answer (OpenAI) instead of a clean skip. This
        is a content-shape check, not a quality fallback: real chunks always
        go to the LLM per this class's failure policy."""
        if not chunks:
            return []
        results: list[ChunkFeatures | None] = [None] * len(chunks)
        llm_indices: list[int] = []
        llm_chunks: list[TerrainChunk] = []
        for i, chunk in enumerate(chunks):
            if not chunk.content.strip():
                results[i] = _EMPTY_CONTENT_EXTRACTOR.extract(chunk)
            else:
                llm_indices.append(i)
                llm_chunks.append(chunk)
        if llm_chunks:
            for i, features in zip(llm_indices, self._extract_batch_llm(llm_chunks)):
                results[i] = features
        return results

    def _extract_batch_llm(self, chunks: list[TerrainChunk]) -> list[ChunkFeatures | None]:
        """Extract features for many *non-empty* chunks in one LLM call.

        Returns a list aligned 1:1 with ``chunks``; an element is ``None`` only
        when that single chunk could not be extracted, so the caller skips just
        that piece. Results are mapped back by an echoed integer ``id`` (never by
        position), so a model that drops or reorders items can't misassign
        features and silently corrupt clustering. On any batch-level problem
        (parse error, missing/duplicate/extra id) the batch is split in half and
        retried down to size 1; fatal config errors (auth) propagate to abort
        the build instead of degrading the whole vault to skips."""
        if len(chunks) == 1:
            try:
                return [self.extract(chunks[0])]
            except Exception as e:  # noqa: BLE001
                if type(e).__name__ in _FATAL_EXTRACT_ERRORS:
                    raise
                self.last_skip_reason = _describe_llm_error(e) or type(e).__name__
                logger.warning(
                    "terrain: single-chunk extract failed, skipping: %s",
                    self.last_skip_reason,
                )
                return [None]
        try:
            return self._extract_batch_call(chunks)
        except Exception as e:  # noqa: BLE001
            if type(e).__name__ in _FATAL_EXTRACT_ERRORS:
                raise
            mid = len(chunks) // 2
            logger.warning(
                "terrain: batch extract of %d chunks failed (%s); splitting %d/%d",
                len(chunks), _describe_llm_error(e), mid, len(chunks) - mid,
            )
            return self._extract_batch_llm(chunks[:mid]) + self._extract_batch_llm(chunks[mid:])

    def _extract_batch_call(self, chunks: list[TerrainChunk]) -> list[ChunkFeatures]:
        response = self._responses_parse(
            input=[
                {"role": "system", "content": _SYSTEM_EXTRACT + _BATCH_SUFFIX},
                {"role": "user", "content": self._batch_prompt(chunks)},
            ],
            text_format=OpenAIChunkFeaturesBatch,
        )
        by_id: dict[int, OpenAIChunkFeaturesItem] = {}
        for item in response.output_parsed.items:
            if item.id in by_id:
                raise ValueError(f"batch returned duplicate id {item.id}")
            by_id[item.id] = item
        if set(by_id) != set(range(len(chunks))):
            raise ValueError(
                f"batch id mismatch: got {sorted(by_id)} for {len(chunks)} chunks"
            )
        return [self._to_features(by_id[i]) for i in range(len(chunks))]

    def _batch_prompt(self, chunks: list[TerrainChunk]) -> str:
        return "\n\n".join(
            f"=== CHUNK id={i} ===\n{self._prompt(chunk)}"
            for i, chunk in enumerate(chunks)
        )

    def _to_features(self, parsed: OpenAIChunkFeatures) -> ChunkFeatures:
        return ChunkFeatures(
            summary=parsed.summary,
            products=parsed.products,
            customers=parsed.customers,
            entities=parsed.entities,
            tags=parsed.tags,
            tag_type_hint=self._coerce_tag_type(parsed.tag_type_hint, parsed),
            theme=(parsed.theme or "General").strip()[:48] or "General",
            subtopic=(parsed.subtopic or parsed.theme or "General").strip()[:48] or "General",
            confidence=max(0.0, min(1.0, parsed.confidence)),
            signals=[
                ChunkSignalDraft(
                    kind=s.kind,
                    title=s.title,
                    summary=s.summary,
                    severity=max(0, min(100, s.severity)),
                    status=s.status,
                    owner=s.owner,
                    due_text=s.due_text,
                    due_date=s.due_date,
                )
                for s in parsed.signals[:5]
            ],
        )

    def _coerce_tag_type(self, raw: str, parsed: OpenAIChunkFeatures) -> TagType:
        if raw in _VALID_TAG_TYPES:
            return raw  # type: ignore[return-value]
        logger.warning(
            "terrain: extractor returned tag_type_hint %r outside v2 enum; "
            "falling back to heuristic",
            raw,
        )
        return heuristic_tag_type(
            ChunkFeatures(
                summary=parsed.summary,
                products=parsed.products,
                customers=parsed.customers,
                entities=parsed.entities,
                tags=parsed.tags,
                tag_type_hint="concept",
                confidence=parsed.confidence,
            )
        )

    def _prompt(self, chunk: TerrainChunk) -> str:
        # Structural Context — fragmented notes need their parent doc,
        # heading path, outbound references, and source-specific properties
        # for the extractor to ground tags correctly. Each line is omitted
        # when its field is empty so the prompt stays short on rich docs.
        lines: list[str] = [
            f"Source: {chunk.source_type}",
            f"Title: {chunk.doc_title}",
        ]
        if chunk.source_parent_title:
            lines.append(f"Parent doc: {chunk.source_parent_title}")
        path_segments = chunk.source_breadcrumb_titles + chunk.heading_path
        if path_segments:
            lines.append(f"Path: {' / '.join(path_segments)}")
        if chunk.wikilinks:
            lines.append(f"Wikilinks: {', '.join(chunk.wikilinks[:24])}")
        if chunk.mentions:
            lines.append(f"Mentions: {', '.join(chunk.mentions[:24])}")
        if chunk.frontmatter_tags:
            lines.append(f"Frontmatter tags: {', '.join(chunk.frontmatter_tags)}")
        if chunk.source_properties:
            props = ", ".join(
                f"{k}={v}"
                for k, v in list(chunk.source_properties.items())[:12]
                if v not in (None, "", [], {})
            )
            if props:
                lines.append(f"Source properties: {props}")
        if self.products:
            lines.append(f"Known products: {', '.join(self.products)}.")
            lines.append("Identify which products apply, or none.")
        lines.extend(
            [
                "",
                "Content:",
                chunk.content[:32000],
            ]
        )
        return "\n".join(lines)


# ── Embeddings ─────────────────────────────────────────────────────


class OpenAIEmbeddingClient(OpenAIClientMixin, EmbeddingClient):
    def __init__(self, model: str = "text-embedding-3-large", dimensions: int | None = None):
        self.model = model
        self.dimensions = dimensions

    def embed(self, text: str, dimensions: int = 64) -> list[float]:
        params = {
            "model": self.model,
            "input": text,
            "encoding_format": "float",
        }
        if self.dimensions is not None:
            params["dimensions"] = self.dimensions
        response = self._client().embeddings.create(**params)
        ledger.record_openai(getattr(response, "usage", None), model=self.model)
        return list(response.data[0].embedding)


# ── Namer (region + tag variants) ──────────────────────────────────


class OpenAIClusterNamer(OpenAIClientMixin, ClusterNamer):
    def __init__(self, store, model: str = "gpt-5.6-luna", *, effort: str | None = None):
        super().__init__(store)
        self.model = model
        self.effort = effort

    # ── Public wrappers (cache-check → network → cache-write) ─────────
    # Each splits into a store-free ``_call_*`` (pure OpenAI round trip) so the
    # compiler's parallel path can run only ``_call_*`` inside a thread pool and
    # keep every ``store`` access on the serial build thread. ``_fingerprint`` is
    # also store-free, so the compiler computes it + ``get_name``/``save_name``
    # serially around the parallel call.

    @staticmethod
    def _avoid_extra(avoid_names: list[str] | None) -> list[str] | None:
        return [f"avoid:{n}" for n in avoid_names] if avoid_names else None

    def name_theme(
        self, items, fallback: str = "General", *, avoid_names: list[str] | None = None
    ) -> tuple[str, str]:
        fingerprint = self._fingerprint(
            items, kind="theme", extra=self._avoid_extra(avoid_names)
        )
        cached = self.store.get_name(fingerprint)
        if cached:
            return cached
        name, summary = self._call_theme(items, fallback, avoid_names=avoid_names)
        self.store.save_name(fingerprint, name, summary)
        return name, summary

    def _call_theme(
        self, items, fallback: str = "General", *, avoid_names: list[str] | None = None
    ) -> tuple[str, str]:
        """Store-free. Safe to run in a worker thread."""
        response = self._responses_parse(
            input=[
                {
                    "role": "system",
                    "content": (
                        "Name a root knowledge theme that groups multiple "
                        "descendant regions. The name must be specific enough to "
                        "tell this theme apart from the other themes in the same "
                        "workspace — prefer the concrete subject matter over a "
                        "broad discipline label. Output a specific 2–4 word "
                        "title-case name and a single sentence summary "
                        "describing what unites the sub-areas. Avoid generic "
                        "names like Documents, Notes, Misc, or General."
                    ),
                },
                {"role": "user", "content": self._prompt(items, fallback, avoid_names=avoid_names)},
            ],
            text_format=ClusterName,
        )
        parsed = response.output_parsed
        return parsed.name, parsed.summary

    def name_region(
        self, items, fallback: str = "Loose Notes", *, avoid_names: list[str] | None = None
    ) -> tuple[str, str]:
        fingerprint = self._fingerprint(
            items, kind="region", extra=self._avoid_extra(avoid_names)
        )
        cached = self.store.get_name(fingerprint)
        if cached:
            return cached
        name, summary = self._call_region(items, fallback, avoid_names=avoid_names)
        self.store.save_name(fingerprint, name, summary)
        return name, summary

    def _call_region(
        self, items, fallback: str = "Loose Notes", *, avoid_names: list[str] | None = None
    ) -> tuple[str, str]:
        """Store-free. Safe to run in a worker thread."""
        response = self._responses_parse(
            input=[
                {
                    "role": "system",
                    "content": (
                        "Name a semantic region grouping multiple related knowledge "
                        "chunks. Output a specific 2–4 word title-case name and a "
                        "single sentence summary. Avoid generic names like Documents, "
                        "Notes, Misc, or General."
                    ),
                },
                {"role": "user", "content": self._prompt(items, fallback, avoid_names=avoid_names)},
            ],
            text_format=ClusterName,
        )
        parsed = response.output_parsed
        return parsed.name, parsed.summary

    def name_tag(
        self,
        items,
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
        label, blurb = self._call_tag(
            items, fallback, region_name=region_name, region_terms=region_terms
        )
        # We store via the same cluster_names table for cache reuse.
        self.store.save_name(fingerprint, label, blurb)
        return label, blurb

    def _call_tag(
        self,
        items,
        fallback: str = "General",
        *,
        region_name: str | None = None,
        region_terms: list[str] | None = None,
    ) -> tuple[str, str]:
        """Store-free. Safe to run in a worker thread."""
        response = self._responses_parse(
            input=[
                {
                    "role": "system",
                    "content": (
                        "Name a tag covering a tight subset of related knowledge "
                        "chunks. Output a specific 1–2 word title-case label and a "
                        "short blurb (one phrase). The tag sits inside a larger "
                        "region; frame the blurb through that region lens when "
                        "region context is provided, and be more specific than the "
                        "region. Avoid generic labels like Documents, Notes, Misc, "
                        "or General."
                    ),
                },
                {
                    "role": "user",
                    "content": self._prompt(
                        items,
                        fallback,
                        region_name=region_name,
                        region_terms=region_terms or [],
                    ),
                },
            ],
            text_format=TagName,
        )
        parsed = response.output_parsed
        return parsed.label, parsed.blurb

    # ── Stage 3: compiled notes (LLM overrides for ClusterNamer) ──────

    def compile_tag_note(
        self,
        label: str,
        blurb: str | None,
        members,
        *,
        region_name: str | None = None,
    ) -> str:
        user = self._compile_prompt(label, blurb, members, region_name=region_name)
        response = self._responses_parse(
            input=[
                {
                    "role": "system",
                    "content": (
                        "Synthesize a 2-3 paragraph compiled note about a tag "
                        "from its member knowledge chunks. Write for an AI "
                        "assistant that will retrieve the note as grounded "
                        "context. Be specific and concrete — name the products, "
                        "people, decisions, and open questions that appear "
                        "across members. Do not hedge ('it seems', 'might'). "
                        "Do not use bullet lists. If region context is "
                        "provided, frame the synthesis through that lens."
                    ),
                },
                {"role": "user", "content": user},
            ],
            text_format=CompiledNote,
        )
        return response.output_parsed.text.strip()

    def compile_region_note(
        self,
        name: str,
        summary: str | None,
        members,
        *,
        child_tag_blurbs: list[str] | None = None,
    ) -> str:
        user = self._compile_region_prompt(
            name, summary, members, child_tag_blurbs or []
        )
        response = self._responses_parse(
            input=[
                {
                    "role": "system",
                    "content": (
                        "Synthesize a 2-3 paragraph compiled note about a "
                        "knowledge region from (a) the synthesized blurbs of "
                        "its child tags and (b) a sample of member chunks. "
                        "Write for an AI assistant that will retrieve the "
                        "note as grounded context. Be specific. Surface "
                        "concrete facts, decisions, and the kinds of "
                        "questions a user might ask about this region. No "
                        "bullet lists. No hedging."
                    ),
                },
                {"role": "user", "content": user},
            ],
            text_format=CompiledNote,
        )
        return response.output_parsed.text.strip()

    def compile_entity_blurb(
        self,
        label: str,
        entity_type: str,
        members,
    ) -> str:
        user = self._compile_entity_prompt(label, entity_type, members)
        response = self._responses_parse(
            input=[
                {
                    "role": "system",
                    "content": (
                        "Write a 1-2 paragraph compiled note about a specific "
                        "entity (a person, product, project, customer, or "
                        "concept) mentioned across multiple knowledge chunks. "
                        "Write for an AI assistant that will retrieve the "
                        "note as grounded context. Be specific: name the "
                        "concrete role, relationships, decisions, and open "
                        "questions that involve this entity. No bullet lists. "
                        "No hedging."
                    ),
                },
                {"role": "user", "content": user},
            ],
            text_format=CompiledNote,
        )
        return response.output_parsed.text.strip()

    def _compile_entity_prompt(
        self,
        label: str,
        entity_type: str,
        members,
    ) -> str:
        lines = [
            f"Entity label: {label}",
            f"Entity type: {entity_type}",
            "",
            "Member chunks that reference this entity (most representative first):",
        ]
        for item in members[:10]:
            f = item.features
            lines.extend(
                [
                    f"- Summary: {f.summary}",
                    f"  Co-mentioned: {', '.join((f.entities + f.products + f.customers)[:6])}",
                ]
            )
        return "\n".join(lines)

    def _compile_prompt(
        self,
        label: str,
        blurb: str | None,
        members,
        *,
        region_name: str | None,
    ) -> str:
        lines = [f"Tag label: {label}"]
        if blurb:
            lines.append(f"Existing short blurb: {blurb}")
        if region_name:
            lines.append(f"Parent region: {region_name}")
        lines.append("")
        lines.append("Member chunks (most representative first):")
        for item in members[:12]:
            f = item.features
            lines.extend(
                [
                    f"- Summary: {f.summary}",
                    f"  Entities: {', '.join(f.entities[:6])}",
                    f"  Tags: {', '.join(f.tags[:6])}",
                ]
            )
        return "\n".join(lines)

    def _compile_region_prompt(
        self,
        name: str,
        summary: str | None,
        members,
        child_tag_blurbs: list[str],
    ) -> str:
        lines = [f"Region name: {name}"]
        if summary:
            lines.append(f"Existing one-line summary: {summary}")
        if child_tag_blurbs:
            lines.append("")
            lines.append("Child tag blurbs:")
            for b in child_tag_blurbs[:25]:
                lines.append(f"- {b}")
        lines.append("")
        lines.append("Sample member chunks:")
        for item in members[:8]:
            f = item.features
            lines.extend(
                [
                    f"- Summary: {f.summary}",
                    f"  Tags: {', '.join(f.tags[:6])}",
                ]
            )
        return "\n".join(lines)

    def _prompt(
        self,
        items,
        fallback: str,
        *,
        region_name: str | None = None,
        region_terms: list[str] | None = None,
        avoid_names: list[str] | None = None,
    ) -> str:
        lines = [f"Fallback if genuinely unclassifiable: {fallback}", ""]
        if avoid_names:
            lines.extend(
                [
                    "Names already used by sibling regions in this workspace: "
                    + "; ".join(avoid_names),
                    "Choose a name that is clearly distinct from — and more specific "
                    "than — every name above. Do not reuse or lightly reword them.",
                    "",
                ]
            )
        if region_name:
            lines.extend(
                [
                    f"Region lens: {region_name}",
                    f"Region defining terms: {', '.join((region_terms or [])[:5])}",
                    "Interpret the chunk from this region's perspective.",
                    "",
                ]
            )
        for item in items[:10]:
            f = item.features
            lines.extend(
                [
                    f"Summary: {f.summary}",
                    f"Products: {', '.join(f.products[:5])}",
                    f"Customers: {', '.join(f.customers[:5])}",
                    f"Entities: {', '.join(f.entities[:8])}",
                    f"Tags: {', '.join(f.tags[:8])}",
                    "",
                ]
            )
        return "\n".join(lines)
