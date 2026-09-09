# Mnemify — Technical Overview

A cross-cutting tour: how a document gets from a SaaS tool into the 3D brain map,
and the machinery that ties the backend and frontend together. For the detailed
backend internals see [`BACKEND.md`](BACKEND.md); for the React app see
[`FRONTEND.md`](FRONTEND.md).

---

## The three tiers

```
  ┌── Tier 0: HARVEST ──────────┐   ┌── Tier 1: COMPILE ───────────────┐   ┌── Tier 2: SURFACE ───────────┐
  │  Notion / Confluence / Jira │   │  chunk → extract → embed →       │   │  FastAPI: /api/terrain/*     │
  │  Obsidian                   │ → │  cluster → layout → name →       │ → │  React: 3D hex brain map     │
  │  fetch · hash · dedup ·     │   │  derive v2 BrainMap → bake v3    │   │  + connect/harvest/compile   │
  │  store native + .md sidecar │   │  hex render-data                 │   │  surfaces                    │
  └── deterministic, no LLM ────┘   └── OpenAI (or `local` no-net) ────┘   └── (planned: MCP, BYOK) ─────┘
        ↓ .mnemify/raw/                  ↓ .mnemify/terrain.json            ↓ http://127.0.0.1:8783
          .mnemify/normalized/             .mnemify/render-data.json
          harvest-manifest.db                 terrain.db
```

Everything Mnemify generates lives under `.mnemify/` (gitignored). A
compile never writes into the repo working tree.

---

## End-to-end data flow

1. **Harvest.** `mnemify harvest` (or the `/api/harvest` UI flow) runs each
   enabled source plugin: list documents → filter on metadata → fetch the
   survivors concurrently → hash → skip if unchanged → write the raw bytes
   (`.mnemify/raw/<source>/<shard>/<id>.<ext>`), a clean-markdown sidecar
   (`.mnemify/normalized/.../<id>.md`), and a row in the SQLite manifest
   (`.mnemify/harvest-manifest.db`). An append-only JSONL audit log records
   every event. Fully deterministic — no LLM, no tokens.

2. **Compile.** `mnemify terrain build` (or `/api/terrain/build`) reads the
   `active` manifest rows + their normalized markdown and runs the terrain
   pipeline: chunk the docs → extract features per chunk (summary, tags,
   entities, …) → embed → cluster into `(theme → sub-region → tag)` → lay out on
   the world plane → name each cluster → derive the **v2 BrainMap**
   (`terrain.json`: the 3-level tree + edges + highlights + stats) and the
   companion **notes registry** (`mocknotes.json`) → validate → bake the **v3
   hex render-data** (`render-data.json`: the honeycomb the 3D map renders).
   Feature/embedding/naming results are cached in `terrain.db`, so re-compiles
   only redo what changed. `--ai-mode local` runs the whole thing with no
   network and no API key.

3. **Surface.** `mnemify up` (or `./run.sh` from the repo root) starts the
   FastAPI server: it serves the brain-map JSON (`GET /api/terrain`,
   `/api/terrain/notes`, `/api/terrain/render-data`), the harvested-docs and
   connections APIs, streams harvest/compile progress over SSE, and — in
   `up` mode — hosts the built React SPA. The React app fetches
   `/api/terrain/render-data`, builds lookup indexes, and renders the 3D hex map
   (`brainMap/` — React Three Fiber + bloom + N8AO); if there's nothing
   compiled yet it shows the connect → harvest → compile onboarding screen.

---

## The SSE / event-bus architecture

Both long-running operations (harvest, compile) stream progress to the UI the
same way:

- **`event_bus.py` / `compile_bus.py`** — an in-process pub/sub with a small
  replay ring buffer. A new SSE subscriber gets the recent buffer replayed
  before it starts seeing live events, so a tab that reconnects mid-run isn't
  blind.
- **`orchestrator.py` / `compile_orchestrator.py`** — the synchronous work
  (a harvest, a `TerrainCompiler.build()`) runs in a worker thread
  (`asyncio.to_thread`); its progress callback hops back to the event loop via
  `loop.call_soon_threadsafe` and publishes onto the bus. A sliding-window
  `_Rate` (in `_rate.py`) turns the event stream into an events/sec figure the
  UI smooths into an ETA. Cancellation is cooperative — a `threading.Event` the
  worker checks between units of work.
- **`routes_harvest.py` / `routes_terrain.py`** — `GET /api/{harvest,terrain}/stream`
  return `EventSourceResponse`s that emit a `snapshot` event, then forward bus
  events (serialised by the shared `_json` helper in `_sse.py`).
- **Frontend** — `useHarvestStream` / `useCompileStream` wrap `EventSource`;
  the polled `GET /api/{harvest,terrain}/current` snapshot is the fallback
  between SSE connects.

---

## On-disk state (`.mnemify/`)

| Path | What |
|---|---|
| `raw/<source>/<shard>/<id>.<ext>` | Raw fetched bytes — Notion JSON, Confluence XHTML, Jira JSON, Obsidian markdown (byte-for-byte) |
| `normalized/<source>/<shard>/<id>.md` | Clean-markdown sidecar per document — body text only, no frontmatter; metadata lives in the manifest |
| `harvest-manifest.db` | SQLite — one row per document (`raw_path`, `normalized_path`, byte counts, status, a `metadata` JSON blob), plus `harvest_runs` |
| `harvest-log.jsonl` | Append-only JSONL audit log — `harvest_started`, `harvested`, `skipped`, `harvest_failed`, `deleted_at_source`, `attachment_downloaded`, `harvest_completed` |
| `terrain.json` | v2 BrainMap — the theme → sub-region → tag tree, region/tag edges, highlights, stats |
| `mocknotes.json` | v2 notes registry — one `Note` per source doc (title, source, tagIds, excerpt, …) |
| `render-data.json` | v3 hex render-data (`cortex.brain-map.hex`, version 3) — regions, hex instances, tag spires, arcs, palette, shader params |
| `terrain.db` | SQLite — feature cache, embedding cache, compile run history, chunk assignments |
| `mnemify.yaml` | (project root or `~/.mnemify/`) source config — which sources are enabled, scopes, filters; tokens go in `.env`, not here |

---

## Schemas as contracts

`backend/src/terrain/models.py` is the single source of truth for the v2
brain-map: the same Pydantic types power the in-memory pipeline *and* validate
the on-disk `terrain.json` / `mocknotes.json` (id-prefix invariants, value
ranges, `tag.frequency ↔ noteIds` consistency, tree children-xor-tags, edge
endpoints exist, stats totals match — cross-file invariants in
`validate_bidirectional()`). Export the JSON Schema with
`mnemify terrain schema --out brain-map.schema.json`.

The v3 render-data schema (`cortex.brain-map.hex`, version 3) is produced by
`backend/src/terrain/_bake_v3.py` and consumed by the frontend's
`brainMap/types.ts`. The frontend rejects any other `version`.

---

## The harvester plugin contract

Adding a source means implementing `SourcePlugin` (`backend/src/harvester/__init__.py`)
— `health_check()`, `list_documents(since)` → `DocRef[]`, `fetch_document(DocRef)` →
`RawDocument`, `mark_harvested(...)` (optional write-back) — and registering a
factory with `register_plugin("<name>", factory)` in the package's `__init__.py`.
The orchestrator, manifest, filtering, and SSE plumbing are all source-agnostic.
`gmail` and `calendar` plugins exist in-tree but aren't wired into the registry
(or committed) yet — see `docs/BACKLOG.md` / `docs/ROADMAP.md`.
