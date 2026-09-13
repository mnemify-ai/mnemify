from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceDocument(BaseModel):
    id: str
    source_type: str
    source_id: str
    title: str
    source_url: str | None = None
    source_modified: str | None = None
    normalized_path: str | None = None
    metadata: dict = Field(default_factory=dict)
    content: str = ""


class TerrainChunk(BaseModel):
    id: str
    doc_id: str
    source_type: str
    source_id: str
    doc_title: str
    source_url: str | None = None
    source_parent_id: str | None = None
    source_parent_title: str | None = None
    source_ancestor_ids: list[str] = Field(default_factory=list)
    source_breadcrumb_titles: list[str] = Field(default_factory=list)
    heading_path: list[str] = Field(default_factory=list)
    content: str
    content_hash: str
    region_assignments: list[str] = Field(default_factory=list)
    # Structural references — populated by per-source chunkers. All
    # default-empty so old persisted chunks load unchanged. Used by the
    # extractor prompt, embedding text, and the clusterer's reference-affinity
    # blend.
    wikilinks: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    frontmatter_tags: list[str] = Field(default_factory=list)
    source_properties: dict = Field(default_factory=dict)


TagType = Literal[
    "concept", "technology", "person", "product", "event", "metric", "place"
]

AttentionSignalKind = Literal[
    "todo", "risk", "decision", "open_question", "owner", "recent_change"
]

# Content-derived subset of AttentionSignalKind — excludes "recent_change",
# which is computed structurally from source_modified, never from an LLM.
ChunkSignalKind = Literal["todo", "risk", "decision", "open_question", "owner"]

AttentionLevel = Literal["none", "low", "medium", "high", "critical"]


class ChunkSignalDraft(BaseModel):
    """One attention signal as drafted by the per-chunk feature extractor
    (LLM modes) before it's grounded into a full AttentionSignal with
    id/source ids (see src.terrain.utils.attention). Local heuristic mode
    never populates this — ChunkFeatures.signals stays empty and
    extract_attention_signals falls back to regex extraction."""

    kind: ChunkSignalKind
    title: str
    summary: str
    severity: int = Field(default=0, ge=0, le=100)
    status: Literal["open", "resolved"] = "open"
    owner: str | None = None
    # Deadline, when the text states one. ``due_text`` is the verbatim phrase
    # ("by end of April", "in 1 week"); ``due_date`` is ISO YYYY-MM-DD and only
    # set by the LLM when an absolute date appears literally — relative phrases
    # are resolved at grounding time against the doc's authored date, because
    # drafts are cached by content hash and must stay wall-clock independent
    # (see src.terrain.utils.deadlines).
    due_text: str | None = None
    due_date: str | None = None


class AttentionSignal(BaseModel):
    id: str
    kind: AttentionSignalKind
    title: str
    summary: str
    severity: int = Field(default=0, ge=0, le=100)
    status: str = "open"
    owner: str | None = None
    due_text: str | None = None
    due_date: str | None = None
    source_note_ids: list[str] = Field(default_factory=list)
    source_chunk_ids: list[str] = Field(default_factory=list)
    created_or_updated_at: str | None = None


class ChunkFeatures(BaseModel):
    summary: str
    products: list[str] = Field(default_factory=list)
    customers: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    tag_type_hint: TagType = "concept"
    # Legacy extractor hints used by local naming fallbacks. Recursive HDBSCAN
    # now decides rendered tree depth.
    theme: str = "General"
    subtopic: str = "General"
    confidence: float = 0.6
    # LLM-drafted operational signals (todo/risk/decision/open_question/owner)
    # grounded into full AttentionSignal objects in src.terrain.utils.attention.
    # Empty for local heuristic mode, which falls back to regex extraction there.
    signals: list[ChunkSignalDraft] = Field(default_factory=list)


class EnrichedChunk(BaseModel):
    chunk: TerrainChunk
    features: ChunkFeatures
    embedding: list[float]


class ClusterTreeNode(BaseModel):
    id: str
    name: str = ""
    position: Position = Field(default_factory=lambda: Position(x=0.0, z=0.0))
    height: int = Field(default=1, ge=0, le=100)
    chunk_ids: list[str] = Field(default_factory=list)
    children: list["ClusterTreeNode"] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────
# Section B — v2 knowledge-map output types
# ─────────────────────────────────────────────────────────────────────


class Position(BaseModel):
    x: float
    z: float


class Offset(BaseModel):
    dx: float
    dz: float


class Owner(BaseModel):
    name: str
    role: str


class CompilerProvenance(BaseModel):
    version: str
    extractor: str
    clusterer: str


class Bounds(BaseModel):
    minX: float
    maxX: float
    minZ: float
    maxZ: float
    maxElevation: int = 100


class Deltas(BaseModel):
    tags: float = 0.0
    notes: float = 0.0
    edges: float = 0.0


class Stats(BaseModel):
    regions: int
    subRegionsTotal: int = 0
    tagsTotal: int
    notes: int
    sources: int
    edges: int
    deltas: Deltas = Field(default_factory=Deltas)


class Highlights(BaseModel):
    godTags: list[str] = Field(default_factory=list)
    bridgeTags: list[str] = Field(default_factory=list)
    trendingTags: list[str] = Field(default_factory=list)
    isolatedTags: list[str] = Field(default_factory=list)


class AggregateCounts(BaseModel):
    notes: int = 0
    sources: int = 0
    tags: int = 0
    subRegions: int = 0


class RegionWeight(BaseModel):
    """Weighted membership of a tag/region in a top-level region.

    Models many-to-many membership: a tag (or sub-region) relates to several
    top-level regions with a semantic-cosine strength in [0,1]. Exactly one
    entry per owner is the ``isHome`` region — the single region used for hex
    placement (the spatial partition is never broken).
    """

    regionId: str
    weight: float = Field(ge=0, le=1)
    isHome: bool = False


class Tag(BaseModel):
    id: str = Field(pattern=r"^tag\.")
    label: str
    type: TagType
    frequency: int = Field(ge=0)
    recencyScore: float = Field(ge=0, le=1)
    degree: int = Field(ge=0)
    elevation: int = Field(ge=0, le=100)
    offset: Offset
    noteIds: list[str]
    linkedTagIds: list[str] = Field(default_factory=list)
    regionWeights: list[RegionWeight] = Field(default_factory=list)
    attentionScore: float = Field(default=0.0, ge=0, le=100)
    attentionLevel: AttentionLevel = "none"
    signals: list[AttentionSignal] = Field(default_factory=list)
    blurb: str | None = None
    # Stage 3 — compiled notes for chatbot retrieval. The frontend keeps
    # rendering ``blurb`` (the short phrase); the chatbot's retrieval layer
    # uses ``compiled_note`` (top-N, LLM-synthesized) or
    # ``compiled_note_extractive`` (long-tail fallback). Embedding is over
    # whichever of the two is present.
    compiled_note: str | None = None
    compiled_note_extractive: str | None = None
    embedding: list[float] | None = None

    @model_validator(mode="after")
    def _frequency_matches_notes(self) -> "Tag":
        if self.frequency != len(self.noteIds):
            raise ValueError(
                f"tag {self.id}: frequency {self.frequency} != "
                f"len(noteIds) {len(self.noteIds)}"
            )
        return self


class TreeNode(BaseModel):
    id: str
    name: str
    level: int = Field(ge=0)
    parentId: str | None = None
    position: Position | None = None
    height: int = Field(default=1, ge=0, le=100)
    chunk_ids: list[str] = Field(default_factory=list)
    summary: str
    color: str | None = None
    accent: str | None = None
    center: Position
    radius: float = Field(gt=0)
    aggregateCounts: AggregateCounts
    elevation: int = Field(ge=0, le=100)
    children: list["TreeNode"] = Field(default_factory=list)
    tags: list[Tag] = Field(default_factory=list)
    regionWeights: list[RegionWeight] = Field(default_factory=list)
    attentionScore: float = Field(default=0.0, ge=0, le=100)
    attentionLevel: AttentionLevel = "none"
    signals: list[AttentionSignal] = Field(default_factory=list)
    # Stage 3 — note-aware region synthesis (one LLM call per region,
    # uses child tag blurbs as input). Frontend keeps using ``summary``;
    # the chatbot uses ``compiled_note`` (with ``embedding``) for retrieval.
    compiled_note: str | None = None
    embedding: list[float] | None = None

    @model_validator(mode="after")
    def _children_xor_tags(self) -> "TreeNode":
        has_children = bool(self.children)
        has_tags = bool(self.tags)
        if has_children and has_tags:
            raise ValueError(
                f"node {self.id}: must not have both children and tags "
                f"(has_children={has_children}, has_tags={has_tags})"
            )
        return self


RegionEdgeType = Literal[
    "applied-in", "informed-by", "uses", "depends-on", "co-occurs"
]
TagEdgeType = Literal[
    "co-occurs", "uses", "depends-on", "succeeds", "refers-to"
]


class RegionEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    type: RegionEdgeType
    weight: float = Field(ge=0, le=1)
    noteCount: int = Field(ge=0)
    rationale: str


class TagEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    type: TagEdgeType
    weight: float = Field(ge=0, le=1)
    noteCount: int = Field(ge=0)
    crossRegion: bool


class Edges(BaseModel):
    regionEdges: list[RegionEdge] = Field(default_factory=list)
    tagEdges: list[TagEdge] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────
# Section B+ — flat graph view (Stage 4) — chatbot-traversable
# ─────────────────────────────────────────────────────────────────────
#
# The existing tree + Edges is great for the frontend hex map but
# expensive for the chatbot to traverse. The flat GraphView re-indexes
# the same data into typed nodes (region/tag/note, plus entity from
# Stage 4.5) and edges with explicit ``provenance`` and ``confidence``
# fields so the chatbot can reason about *why* two things are connected.
# Additive — the frontend ignores GraphView.

GraphNodeType = Literal["region", "tag", "note", "entity", "signal"]

EdgeProvenance = Literal["extracted", "inferred", "ambiguous"]

GraphEdgeType = Literal[
    "contains",          # region → tag (or region → child region)
    "co-occurs",         # tag ↔ tag (existing tagEdges)
    "linked-to",         # tag ↔ tag (via Tag.linkedTagIds)
    "region-rel",        # region ↔ region (existing regionEdges)
    "belongs-to",        # note → tag
    "mentions",          # note → entity  (Stage 4.5)
    "belongs_to_theme",  # entity → tag   (Stage 4.5)
    "co-mention",        # entity ↔ entity (Stage 4.5)
    "has-signal",        # region/tag/note → signal
]


class GraphNode(BaseModel):
    id: str
    type: GraphNodeType
    label: str
    summary: str = ""
    embedding: list[float] | None = None
    # ``context_embedding`` is the neighborhood-aware blend produced by
    # Stage 4.6; ``embedding`` stays the raw text embedding from Stage 3.
    context_embedding: list[float] | None = None
    homeRegionId: str | None = None
    layer: int = 0  # 0=note, 1=entity, 2=tag, 3=region
    leidenCommunityId: int | None = None
    centrality: float = 0.0
    # Recency in [0,1], stamped at graph-emission time. Only tag nodes carry
    # a real value today (from Tag.recencyScore); other layers default to 0.
    # Consumed by the /api/ask four-signal rerank.
    recency: float = 0.0
    # Optional source-type label only meaningful for entity nodes.
    entityType: str | None = None
    # Optional metadata for attention signal nodes.
    signalKind: AttentionSignalKind | None = None
    severity: int | None = Field(default=None, ge=0, le=100)
    status: str | None = None
    owner: str | None = None
    sourceNoteIds: list[str] = Field(default_factory=list)
    sourceChunkIds: list[str] = Field(default_factory=list)


class GraphEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    type: GraphEdgeType
    weight: float = Field(ge=0, le=1)
    provenance: EdgeProvenance
    confidence: float = Field(ge=0, le=1)


class SurprisingEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    score: float = Field(ge=0)


class GraphView(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    surprisingConnections: list[SurprisingEdge] = Field(default_factory=list)


class KnowledgeMap(BaseModel):
    version: Literal[2] = 2
    schemaName: Literal["cortex.brain-map"] = "cortex.brain-map"
    workspace: str
    owner: Owner
    generatedAt: str
    compiler: CompilerProvenance
    bounds: Bounds
    stats: Stats
    highlights: Highlights
    tree: list[TreeNode]
    edges: Edges
    # Stage 4+ — flat chatbot-traversable view of the same data. The
    # frontend rendering pipeline (v3 bake) ignores this field; the
    # ``/api/ask`` retrieval reads it.
    graph: GraphView | None = None

    @model_validator(mode="after")
    def _cross_entity_invariants(self) -> "KnowledgeMap":
        # Collect IDs from the tree (single pass).
        node_ids: list[str] = []
        tag_ids: list[str] = []
        all_tags: list[Tag] = []

        def _walk(node: TreeNode) -> None:
            node_ids.append(node.id)
            for tag in node.tags:
                tag_ids.append(tag.id)
                all_tags.append(tag)
            for child in node.children:
                _walk(child)

        for root in self.tree:
            _walk(root)

        # Uniqueness.
        if len(set(node_ids)) != len(node_ids):
            dupes = [i for i in node_ids if node_ids.count(i) > 1]
            raise ValueError(f"duplicate node ids: {sorted(set(dupes))}")
        if len(set(tag_ids)) != len(tag_ids):
            dupes = [i for i in tag_ids if tag_ids.count(i) > 1]
            raise ValueError(f"duplicate tag ids: {sorted(set(dupes))}")

        tag_id_set = set(tag_ids)
        top_level_ids = {n.id for n in self.tree}

        # stats.tagsTotal must equal the number of leaf tags.
        if self.stats.tagsTotal != len(tag_ids):
            raise ValueError(
                f"stats.tagsTotal {self.stats.tagsTotal} != "
                f"actual tag count {len(tag_ids)}"
            )

        # Region-edge endpoints must be top-level node IDs.
        for edge in self.edges.regionEdges:
            if edge.from_ not in top_level_ids:
                raise ValueError(
                    f"regionEdge.from {edge.from_!r} is not a top-level node"
                )
            if edge.to not in top_level_ids:
                raise ValueError(
                    f"regionEdge.to {edge.to!r} is not a top-level node"
                )

        # Tag-edge endpoints must be existing tag IDs.
        for edge in self.edges.tagEdges:
            if edge.from_ not in tag_id_set:
                raise ValueError(
                    f"tagEdge.from {edge.from_!r} not in tag set"
                )
            if edge.to not in tag_id_set:
                raise ValueError(
                    f"tagEdge.to {edge.to!r} not in tag set"
                )

        # Tag.linkedTagIds must all be real tags.
        for tag in all_tags:
            for linked in tag.linkedTagIds:
                if linked not in tag_id_set:
                    raise ValueError(
                        f"tag {tag.id}: linkedTagIds contains unknown "
                        f"tag id {linked!r}"
                    )

        return self


# ─────────────────────────────────────────────────────────────────────
# Section C — notes registry (companion file mocknotes.json)
# ─────────────────────────────────────────────────────────────────────


NoteSource = Literal[
    "obsidian", "notion", "confluence", "jira", "gmail", "slack", "calendar"
]


class Note(BaseModel):
    id: str = Field(pattern=r"^n-")
    title: str
    source: NoteSource
    sourceUrl: str
    author: str
    # Display name of the last editor when the source reports one and it
    # differs from the creator; None otherwise.
    lastModifiedBy: str | None = None
    # Where inside the source the doc lives (Confluence space key, Jira
    # project key); "" when the source has no such container.
    sourceDetail: str = ""
    createdAt: str
    updatedAt: str
    regionId: str
    primaryTagId: str = Field(pattern=r"^tag\.")
    tagIds: list[str]
    excerpt: str
    wordCount: int = Field(ge=0)


class KnowledgeMapNotes(BaseModel):
    version: Literal[2] = 2
    generatedAt: str
    notes: list[Note]


# ─────────────────────────────────────────────────────────────────────
# Section D — cross-file bidirectional invariants
# ─────────────────────────────────────────────────────────────────────


def validate_bidirectional(knowledge_map: KnowledgeMap, notes: KnowledgeMapNotes) -> None:
    """Enforce tag↔note bidirectional consistency and crossRegion correctness.

    Raises ValueError on first violation, pointing to the specific entity.
    Run after both objects have already passed their own per-model validators.
    """
    # Build indices.
    tag_by_id: dict[str, Tag] = {}
    tag_to_top_level: dict[str, str] = {}  # tag id → containing top-level node id
    all_nodes: list[tuple[TreeNode, str]] = []  # (node, its top-level ancestor id)
    top_level_ids = {root.id for root in knowledge_map.tree}

    def _walk(node: TreeNode, top_id: str) -> None:
        all_nodes.append((node, top_id))
        for tag in node.tags:
            tag_by_id[tag.id] = tag
            tag_to_top_level[tag.id] = top_id
        for child in node.children:
            _walk(child, top_id)

    for root in knowledge_map.tree:
        _walk(root, root.id)

    # Weighted region-membership invariants. regionWeights is additive/optional,
    # so only validate owners that declare it (freshly-compiled maps always do).
    def _check_region_weights(
        owner_kind: str,
        owner_id: str,
        weights: list[RegionWeight],
        home_id: str,
    ) -> None:
        if not weights:
            return
        homes = [w for w in weights if w.isHome]
        if len(homes) != 1:
            raise ValueError(
                f"{owner_kind} {owner_id}: regionWeights must have exactly one "
                f"isHome entry, found {len(homes)}"
            )
        if homes[0].regionId != home_id:
            raise ValueError(
                f"{owner_kind} {owner_id}: home regionWeight is "
                f"{homes[0].regionId!r} but owner lives in {home_id!r}"
            )
        for w in weights:
            if w.regionId not in top_level_ids:
                raise ValueError(
                    f"{owner_kind} {owner_id}: regionWeights references "
                    f"non-top-level region {w.regionId!r}"
                )

    for tid, tag in tag_by_id.items():
        _check_region_weights("tag", tid, tag.regionWeights, tag_to_top_level[tid])
    for node, top_id in all_nodes:
        _check_region_weights("node", node.id, node.regionWeights, top_id)

    notes_by_id = {n.id: n for n in notes.notes}

    # Every note.tagIds[i] must reference an existing tag.
    for note in notes.notes:
        if not note.tagIds:
            raise ValueError(f"note {note.id}: tagIds is empty")
        if note.primaryTagId not in note.tagIds:
            raise ValueError(
                f"note {note.id}: primaryTagId {note.primaryTagId!r} not in "
                f"tagIds {note.tagIds!r}"
            )
        for tid in note.tagIds:
            if tid not in tag_by_id:
                raise ValueError(
                    f"note {note.id}: tagIds contains unknown tag {tid!r}"
                )

    # Every tag.noteIds[j] must reference an existing note.
    # And the set of notes that reference a tag must equal tag.noteIds.
    notes_for_tag: dict[str, set[str]] = {tid: set() for tid in tag_by_id}
    for note in notes.notes:
        for tid in note.tagIds:
            notes_for_tag[tid].add(note.id)

    for tid, tag in tag_by_id.items():
        for nid in tag.noteIds:
            if nid not in notes_by_id:
                raise ValueError(
                    f"tag {tid}: noteIds contains unknown note {nid!r}"
                )
        observed = notes_for_tag[tid]
        declared = set(tag.noteIds)
        if observed != declared:
            missing = declared - observed
            extra = observed - declared
            raise ValueError(
                f"tag {tid}: noteIds mismatch — "
                f"declared but not referenced: {sorted(missing)}; "
                f"referenced but not declared: {sorted(extra)}"
            )

    # tagEdge.crossRegion correctness.
    for edge in knowledge_map.edges.tagEdges:
        a_top = tag_to_top_level.get(edge.from_)
        b_top = tag_to_top_level.get(edge.to)
        actual_cross = a_top != b_top
        if edge.crossRegion != actual_cross:
            raise ValueError(
                f"tagEdge {edge.from_}→{edge.to}: crossRegion={edge.crossRegion} "
                f"but tags live in {a_top!r} and {b_top!r}"
            )


# ─────────────────────────────────────────────────────────────────────
# Section E — build-result type for the compiler API
# ─────────────────────────────────────────────────────────────────────


class KnowledgeMapBuildResult(BaseModel):
    run_id: str
    terrain_path: str       # .mnemify/terrain.json (v2 KnowledgeMap)
    notes_path: str         # .mnemify/mocknotes.json
    render_data_path: str   # .mnemify/render-data.json (v3 hex bake)
    stats: Stats
