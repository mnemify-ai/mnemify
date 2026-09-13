# AGENTS.md — Mnemify Orientation

> Read this before touching any code. This file is a **map to the code**, not
> a substitute for it. It stays intentionally short; the code and its module
> docstrings are the source of truth. If anything here conflicts with the
> code, the code wins.

---

## Where things live

| Area | Path | Notes |
|---|---|---|
| Harvester (Tier 0) | `backend/src/harvester/` | One package per source (`notion/`, `confluence/`, `jira/`, `obsidian/`, `slack/`, `github/`, `_google/`). Plugin contract is `SourcePlugin` in `harvester/__init__.py`: `health_check()`, `list_documents(since)`, `fetch_document(ref)`, optional `mark_harvested()`; register with `register_plugin(name, factory)`. |
| Terrain compiler (Tier 1) | `backend/src/terrain/` | File map below. |
| FastAPI + SSE (Tier 2) | `backend/src/api/` | `__init__.py` builds the app and mounts `frontend/web/dist` if present. Harvest/compile progress streams over SSE from an in-process event bus (`event_bus.py`, `compile_bus.py`) with a replay ring buffer for reconnecting tabs. Schedules (`/api/schedules`) run on an in-process APScheduler — single uvicorn worker only. |
| Chat (`/api/ask`) | `backend/src/api/routes_ask.py`, `ask_retrieval.py`, `ask_chunks.py`, `ask_expansion.py`, `ask_providers.py`, `ask_agent.py` | Flow: `understand_query()` → embed → chunk search over `terrain.db` vectors → graph walk/rerank → bundle (≤15 items) → expand to raw chunk text → SSE `retrieval_debug → citations → delta* → citations_used → done`. The chat-LLM key arrives per request in `Authorization: Bearer` and is never persisted; query embeddings use the server's `OPENAI_API_KEY` so vectors match the compile. Frontend side: `frontend/web/src/ask/`. |
| CLI | `backend/src/cli.py` | `mnemify harvest / terrain build / up / status / inspect / normalize / purge / debug / reset / login`. Run via `uv run mnemify …` from `backend/`. |
| React app | `frontend/web/src/` | `brainMap/` is the self-contained R3F 3D module (`BrainMap.tsx`, `scene/`, `chrome/`, `store.ts`); `app/` is the dashboard shell (`routes.tsx`, `pages/`, `components/`, `api/`, `sse/`, `data/`). Stack: React 18 + Vite 5 + TS strict, Tailwind with CSS-var theme, React Router v6, TanStack Query v5. Vite proxies `/api/*` to `:8783`. |
| Tests | `backend/tests/` (`uv run pytest -q`), `frontend/web/` (`npm test`, `npx tsc -b`) | Live-network harvester tests skip without credentials. |

**On-disk state — everything under `.mnemify/` (gitignored):**

| Path | What |
|---|---|
| `raw/<source>/<shard>/<id>.<ext>` | Raw fetched bytes, byte-for-byte |
| `normalized/<source>/<shard>/<id>.md` | Clean-markdown sidecar per document (body only; metadata lives in the manifest) |
| `harvest-manifest.db` | SQLite: one row per document + `harvest_runs` |
| `harvest-log.jsonl` | Append-only audit log of harvest events |
| `terrain.json` | v2 BrainMap: region → tag tree, graph nodes/edges, entities, attention signals |
| `mocknotes.json` | Note registry (one per source doc) for citations and panels |
| `render-data.json` | v3 hex render-data the 3D map reads — additive-only, no graph/embedding fields |
| `terrain.db` | SQLite cache: features, embeddings, names, positions, compiled notes, chunk vectors, compile runs |

`mnemify.yaml` (project root) holds source config; tokens live in `.env`.

---

## What This Product Is

A **Knowledge Map that is becoming a grounded chatbot.** Users connect
Notion / Confluence / Jira / Obsidian; the pipeline turns harvested documents
into (a) a 3D hex terrain — a spatial browse surface — and (b) a layered
knowledge graph the chatbot retrieves over. Both are derived from the same
compiled brain map; neither is primary over the other going forward.

**The three pillars:**
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

Three tiers:

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
check `git log -p` on the file first — it's probably a known, already-fixed
edge case, or a documented pending gap (below).

**Pending:**
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
  `openDoc` wiring. Recommended approach: resolve entity → home tag.
- Compile-time emission counters (`{stage, regions, tags, entities, edges}`)
  for observability — not yet reported over SSE.

---

## What Not To Do

- **Do not touch `_bake_v3.py` / `render_v3.py`** without reading the
  module and constant comments first — the geometry has documented
  failure modes (e.g. small regions annihilated by warp amplitude) that look
  like bugs but are load-bearing constants.
- **Do not add config files or settings objects** for the clustering/bake
  constants (`MAX_LEAF_CHUNKS`, `HEXES_PER_TAG`, `warp_amp`, etc.). Named
  module constants only, until real-corpus tuning data exists.
- **Do not implement compatibility bridges** to a pre-emergent-tree model. If
  HDBSCAN cluster assignments are missing, raise loudly rather than fall back.
- **Do not let graph/entity/embedding fields leak into `render-data.json`.**
  Stage 4+ output stays in `terrain.json`; `_bake_v3.py` explicitly strips it.
- **Do not revive removed frontend components** (e.g. a standalone
  `ArcsToggle.tsx`, a `Legend.tsx`, `ActivityFeed.tsx` — all removed in the V2
  BrainMap redesign).
- **Do not wholesale-adopt GraphRAG/LightRAG/graphify.** The strategy is
  to cherry-pick one pattern
  at a time into the existing hex-terrain pipeline, never swap the pipeline.

---

## Is Claude Code actually reading this file?

Only if a `CLAUDE.md` at the repo root points here. Claude Code auto-loads
`CLAUDE.md` at session start; it does **not** auto-load `AGENTS.md` on its
own. There is no `CLAUDE.md` in the repo today — add a one-line one that
says "Read AGENTS.md" if you want it picked up automatically.

---

*Last updated: 2026-09-14. The former `docs/` folder was removed; this file
and the per-package READMEs are the only prose docs.*
