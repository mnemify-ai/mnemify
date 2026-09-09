# AGENTS.md — Mnemify Orientation

> Read this before touching any code. This file is a **map to the docs and the
> code**, not a substitute for either. It stays intentionally short. For
> depth, follow the links below — those files are the maintained, current
> source of truth. If anything here conflicts with `docs/` or with the code,
> the code wins, then `docs/`, then this file.

---

## Doc map — read in this order

| Doc | What it's for |
|---|---|
| [`docs/TECHNICAL.md`](docs/TECHNICAL.md) | Cross-cutting tour: the three tiers (Harvest → Compile → Surface), on-disk state under `.mnemify/`, the SSE/event-bus architecture. **Start here.** |
| [`docs/BACKEND.md`](docs/BACKEND.md) | Deep backend reference: harvester internals (§1-§12), SQLite schema, plugin interface, module map. |
| [`docs/terrain_improvements.md`](docs/terrain_improvements.md) | **The terrain pipeline's living spec.** Stage-by-stage plan (chunking → structural context → compiled notes → graph/Leiden → entities → GraphSAGE → chatbot → personal graph → graph APIs), plus an **Applied / Pending TODO log** — the most reliable signal for "is X actually built yet." |
| [`docs/terrain_design_justification.md`](docs/terrain_design_justification.md) | *Why* the terrain design choices were made — read this before proposing to change clustering, graph, or entity architecture. |
| [`docs/terrain_render_pipeline.md`](docs/terrain_render_pipeline.md) | How the region/tag tree becomes the 3D hex island (`_bake_v3.py`). Read before touching layout, height, or Voronoi logic. |
| [`docs/FRONTEND.md`](docs/FRONTEND.md) | React app reference: stack, folder layout, routes, the BrainMap module, wizards, SSE wire protocol. |
| [`docs/RECENT_CHANGES.md`](docs/RECENT_CHANGES.md) | The v0.8 recent-changes feature: `/api/changes` + the "since last compile" boundary, author attribution keys, compile nudge / auto-compile, the map's overlay modes. |
| [`docs/ASK_PIPELINE.md`](docs/ASK_PIPELINE.md) | The `/api/ask` chatbot end-to-end: query understanding → hybrid graph retrieval → raw-chunk expansion → SSE protocol → cited-only citation chips. Read before touching `ask_*.py` or `frontend/web/src/ask/`. |
| [`docs/frontend_improvements.md`](docs/frontend_improvements.md) | Frontend work-in-flight tiers + a "stale references — do not act on these" tombstone list. |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Product/UX roadmap — jobs-to-be-done, what's shipped, what's next. |
| [`docs/BACKLOG.md`](docs/BACKLOG.md) | Small-to-medium engineering follow-ups, mostly backend/harvester. |
| [`docs/TESTING.md`](docs/TESTING.md) | Manual end-to-end test walkthrough against a real backend. |

**Habit to build:** before fixing a bug or extending the terrain pipeline,
grep `docs/terrain_improvements.md` for the relevant Stage and its Applied /
Pending notes. A lot of "obvious bugs" here were already found and fixed
during the v0.5 build — the TODO log records exactly what and why, so you
don't re-discover (or re-break) the same thing.

---

## What This Product Is

A **Knowledge Map that is becoming a grounded chatbot.** Users connect
Notion / Confluence / Jira / Obsidian; the pipeline turns harvested documents
into (a) a 3D hex terrain — a spatial browse surface — and (b) a layered
knowledge graph the chatbot retrieves over. Both are derived from the same
compiled brain map; neither is primary over the other going forward.

**The three pillars (from `terrain_design_justification.md`):**
1. **Legibility** — every connection can explain *why* it exists (edge
   provenance: `extracted` vs `inferred` vs `ambiguous`).
2. **Multi-path triangulation** — the same answer reachable through entities,
   themes, and notes, so the system can corroborate itself.
3. **Local-first** — the user's brain and their API key never leave their
   machine.

**Key invariants that still hold:**
- **Same document, multiple region appearances.** A cross-cutting document
  gets its primary region plus secondary `region_assignments` above a
  similarity threshold — implemented in `clusterer.assign_multi_region()`.
- **Emergent structure, not fixed taxonomy.** Regions/tags/depth emerge from
  HDBSCAN on real embeddings, not hardcoded keyword lists.
- **Uniform node schema** for the region tree (`id, name, position, height,
  chunk_ids, children`) — leaves have `chunk_ids` and empty `children`.
- **LLM names/synthesizes what emerged; it does not determine structure.**
  Clustering is HDBSCAN; naming and compiled-note synthesis are LLM calls
  layered on top, cached by content-hash fingerprint.
- **`render-data.json` is additive-only.** Graph/entity/embedding work
  (Stage 4+) lives in `terrain.json`, never leaks into the v3 hex bake.

---

## Pipeline Overview

```
Harvest → Normalize → Chunk (per-source) → Extract → Embed → Cluster
  → Merge/Region-refine → Name/Compile-notes → Promote entities
  → Build graph (Leiden + confidence) → Context-embed (GraphSAGE-lite)
  → Layout → Emit terrain.json → Bake v3 render-data.json
```

Three tiers, source of truth in `docs/TECHNICAL.md`:

| Tier | Package | LLM? |
|---|---|---|
| 0 — Harvester | `backend/src/harvester/` | No — deterministic |
| 1 — Compiler | `backend/src/terrain/` | Yes (or `--ai-mode local`) |
| 2 — Surface | `backend/src/api/` + `frontend/web/` | No — BYOK |

---

## `backend/src/terrain/` — current file map

```
terrain/
├── pipelines/compiler.py     TerrainCompiler — drives the whole compile:
│                              reader → chunk → extract → embed → cluster →
│                              region_merger → namer → _promote_entities →
│                              _build_graph_view (Leiden) → graph_embed →
│                              layout → emit → validate → bake_v3
├── preprocessing/
│   ├── reader.py              Loads active manifest rows + normalized markdown
│   ├── extractor.py           Local-mode deterministic feature extraction
│   └── chunkers/               Per-source ChunkerRegistry dispatch (Stage 1):
│       markdown_default.py, notion.py, obsidian.py, confluence.py, registry.py
├── agents/
│   ├── openai_clients.py      OpenAI-backed extractor, namer, compiled-note
│                              synthesis, entity blurbs, query understanding
│   ├── claude_cli.py           `ai_mode="claude"` transport — subscription
│                              auth via the local `claude` CLI, not metered API
│   └── claude_clients.py      Shims the OpenAI prompt/parse contract onto claude_cli
├── utils/
│   ├── models.py               Single source of truth: TerrainChunk, ChunkFeatures,
│                              ClusterTreeNode, GraphNode/GraphEdge/GraphView, Entity,
│                              BrainMap, AttentionSignal, etc.
│   ├── embedder.py             EmbeddingClient (real OpenAI `embed`/`embed_batch`)
│                              + LocalHashEmbeddingClient (explicit local/offline mode)
│   ├── clusterer.py             TerrainClusterer — HDBSCAN + recursive _build_node,
│                              nearest-centroid noise absorption, assign_multi_region,
│                              container-backbone clustering (cluster_with_containers)
│   ├── containers.py           Source-native folder path extraction (Obsidian, etc.)
│   ├── region_merger.py        Post-cluster region merge/refine pass
│   ├── namer.py                 ClusterNamer (local heuristic fallback) —
│                              OpenAIClusterNamer (agents/) does the real LLM naming
│   ├── canonicalize.py         Entity-label fuzzy canonicalization (Stage 4.5)
│   ├── attention.py            AttentionSignal / recency / action-item detection
│   ├── graph_embed.py          Stage 4.6 — mean-of-neighbors context_embedding
│   ├── layout.py                Deterministic circular packing, nested_positions()
│   ├── emitter.py               Atomic terrain.json + mocknotes.json writer
│   └── store.py                 SQLite cache (.mnemify/terrain.db): features,
│                              embeddings, names, positions, compiled notes
├── _bake_v3.py                  v2→v3 hex bake core: force-directed region layout,
│                              warped-Voronoi leaf assignment, tag summits, diffusion
└── render_v3.py                  bake_v3() entry point + call sequence
```

**Do not rely on any older description of this tree** (flat `chunker.py` /
`compiler.py` at package root, no `agents/` split) — that shape predates the
v0.5 rewrite (see `git log` around `cbe1b0f`, `V0.5`, `V0.6 Improvements`).

---

## Current status (v0.5/v0.6) — what's real vs pending

The embedder, clusterer, and namer described in older internal notes as
"broken" (fake hash embeddings, HDBSCAN overridden by keyword matching, no
LLM naming) are **fixed** — `EmbeddingClient.embed()` calls real
`text-embedding-3-small`/`-large`, `clusterer.py` has no keyword override
branches, and `OpenAIClusterNamer` does real LLM naming + compiled-note
synthesis. Don't re-diagnose these; if something in this area looks wrong,
check `docs/terrain_improvements.md`'s "Applied" log first — it's probably a
known, already-fixed edge case, or a *documented* pending gap (below).

**Pending, called out explicitly in `docs/terrain_improvements.md`** (check
there before starting work — it may have moved):
- Reference-affinity signals beyond wikilinks/mentions (internal URLs, Notion
  page mentions, Confluence `ac:link`, Jira issue links) — only Obsidian
  really benefits from the sparse-note clustering boost today.
- Entity canonicalization threshold (0.85) undermerges risk for `person`
  labels — needs tightening or a stricter person-specific rule.
- Per-workspace entity-type taxonomy is hardcoded
  (`person/product/project/customer/concept`) — Stage 5.5 generalizes this.
- Confidence-score calibration for `inferred` edges — currently borrows the
  Jaccard weight axis as a trust axis; not validated against a labeled set.
- Citation → hex-map click-through: works for **tag** citations only; entity
  and region citations are non-clickable; note citations need frontend
  `openDoc` wiring. See the "Pending — Citation → hex map feedback loop"
  section for the recommended option (A: resolve entity → home tag).
- Compile-time emission counters (`{stage, regions, tags, entities, edges}`)
  for observability — not yet reported over SSE.

---

## What Not To Do

- **Do not touch `_bake_v3.py` / `render_v3.py`** without reading
  `docs/terrain_render_pipeline.md` first — the geometry has documented
  failure modes (e.g. small regions annihilated by warp amplitude) that look
  like bugs but are load-bearing constants.
- **Do not add config files or settings objects** for the clustering/bake
  constants (`MAX_LEAF_CHUNKS`, `HEXES_PER_TAG`, `warp_amp`, etc.). Named
  module constants only, until real-corpus tuning data exists.
- **Do not implement compatibility bridges** to a pre-emergent-tree model. If
  HDBSCAN cluster assignments are missing, raise loudly rather than fall back.
- **Do not let graph/entity/embedding fields leak into `render-data.json`.**
  Stage 4+ output stays in `terrain.json`; `_bake_v3.py` explicitly strips it.
- **Do not revive frontend items on the `frontend_improvements.md` "stale
  references" tombstone list** (e.g. a standalone `ArcsToggle.tsx`, a
  `Legend.tsx`, `ActivityFeed.tsx` — all removed in the V2 BrainMap redesign).
- **Do not wholesale-adopt GraphRAG/LightRAG/graphify.** Per
  `terrain_design_justification.md`, the strategy is cherry-pick one pattern
  at a time into the existing hex-terrain pipeline, never swap the pipeline.

---

## Is Claude Code actually reading this file?

Yes — via `CLAUDE.md` at the repo root, which just points here. Claude Code
auto-loads `CLAUDE.md` at session start; it does **not** auto-load
`AGENTS.md` on its own. If you rename or move this file, update `CLAUDE.md`'s
pointer too.

---

*Last updated: 2026-08-10. Rewritten to reflect the v0.5/v0.6 pipeline
(agents/ split, graph + entity layer, per-source chunking) and to point at
`docs/` as the maintained reference instead of duplicating it.*
