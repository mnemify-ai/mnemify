# TODO — v2: the static map

> Working document for the next compiler milestone. Product menu lives in
> [`ROADMAP.md`](ROADMAP.md), small follow-ups in [`BACKLOG.md`](BACKLOG.md).
> This file is the design + task list for one feature: **a 3D map that stays
> put when new documents arrive.**

Last updated: 2026-09-07.

---

## 1. Why

Two problems, one root cause.

**Cost.** Around 1,000 documents a daily harvest + compile burns through the
LLM subscription. Most of that spend is *re-synthesis of notes whose content
barely changed*, not analysis of new content. Chunk features and embeddings
are already content-hash cached; the compiled tag/region notes were not
resilient to membership churn (fixed 2026-09-07, see §2), and the churn itself
comes from re-clustering the whole corpus on every compile.

**Product.** A user's mental model of the map should be stable. "Finance is
the region in the north-east" must still be true tomorrow after they add ten
pages. Today every compile runs HDBSCAN from scratch over all chunk
embeddings, so regions can split, merge, and re-tile between runs, even with
no new documents. That makes the map a *report*, not a *place*.

The v2 goal: **adding documents does not move the map. New land appears only
when there is enough evidence for a new region, and the user can see it
happen.**

---

## 2. Shipped today (2026-09-07) — caching fixes

These are done and tested on branch `V9.1`; listed so the design below can
assume them.

- **Calendar-free cache keys.** Attention-signal severity carries a
  deadline boost computed against *today*, so it was invalidating tag and
  region notes whenever a due date crossed the 7-day line. Cache keys now use
  `signals_cache_lines` (kind/title/status/owner, no severity) —
  `backend/src/terrain/utils/attention.py`. Prompts still see severity.
- **Overlap-tolerant compiled-note reuse.** On an exact-key miss, the
  compiler looks for a cached note of the same kind whose *synthesized member
  set* overlaps the current one by Jaccard ≥ `TERRAIN_NOTE_REUSE_OVERLAP`
  (default 0.9). A hit is re-saved under the new exact key with the original
  members carried forward and a `drift` counter bumped across the whole
  family; after `TERRAIN_NOTE_REUSE_MAX_DRIFT` (default 3) reuses the note is
  force re-synthesized. Extractive (no-LLM) notes never fuzzy-match.
  `TerrainCompiler._lookup_compiled_note`,
  `TerrainStore.find_similar_compiled_note`, new table
  `compiled_note_members`.

- **Per-step reasoning effort** (`extract_effort`, `name_effort` in the
  compile settings + UI; defaults low / medium). One setting drives OpenAI
  `reasoning.effort`, Claude API `output_config.effort`, and Claude CLI
  `--effort`. Not part of any cache key. Measured on the dev corpus: chunk
  extraction is ~90% of a fresh compile's tokens, and at the provider default
  every one of those calls thinks at length — this is the main subscription
  lever. `backend/src/terrain/agents/usage.py:effort_for`.
- **Per-stage LLM usage ledger.** Every transport records tokens per call,
  tagged by stage (extract / embed / merge / name / notes). Stored in
  `terrain_runs.counts.llm_usage` for completed *and* failed runs, logged as
  one summary line, and shown as an "LLM usage" section on the compile report.
- **Resumable quota stops.** A Claude CLI usage/rate limit, or an SDK
  `RateLimitError`, aborts immediately (chunks already extracted are cached)
  and is stored with the `Usage limit reached` prefix; the compile page shows
  a banner with *Resume compile*. Auth and missing-CLI failures get their own
  wording and are not offered as resumable.
- **Recommended configuration note** in Settings → Compile, next to the
  effort controls.

What this does **not** fix: node ids still encode exact membership, the map
geometry still re-derives every compile, and the region cache key still
embeds child-note previews (fuzzy path catches it, exact path stays brittle).

Measured but deliberately not done: extraction batch 16 saves ~10% of
extraction input (fixed schema+system overhead is ~24% at batch 8); provider
prompt caching is short-lived (5 min) and would help only the API modes;
Batch/Flex tiers need a scheduler and were declined for now.

---

## 3. Current state of the code (facts to design against)

| Concern | Where | Behaviour today |
|---|---|---|
| Cluster node id | `utils/clusterer.py` `_node_id_from_ids` | `node_<hash(path \| sorted chunk_ids)>` — any membership change → new id |
| Chunk id | `preprocessing/chunkers/markdown_default.py` | `chunk_<hash(doc_id:index:content_hash)>` — editing a chunk changes its id |
| Tag id / region id | `pipelines/compiler.py` `_derive_tree` | `tag.<leaf node id>` / `<node id>` — inherit the churn above |
| Clustering | `pipelines/compiler.py` `build()` | `TerrainClusterer.cluster[_with_containers]` runs unconditionally on every compile over all enriched chunks |
| Container seeding | `utils/clusterer.py` `cluster_with_containers` | Folder paths give a stable top-level backbone; HDBSCAN runs *inside* each container — leaf churn is where tags live |
| Persisted tree | `utils/store.py` `cluster_tree_nodes` | Written by `save_assignments` every run, **never read** |
| Layout | `utils/layout.py`, `layout_seeds` table | Seeds are persisted per node id — useless once the id changes |
| Region merger | `utils/region_merger.py` | Up to 40 LLM pair judgements per compile, no cache; merges disabled when containers exist |
| Document load | `preprocessing/reader.py` `TerrainReader.load` | Loads every active manifest row; no since-boundary |
| Last compile time | `utils/store.py` `get_last_compile_time` | Exists; used only by `/api/changes` |
| Noise handling | `utils/clusterer.py` `_groups_from_labels` | HDBSCAN noise points are absorbed into the nearest centroid with a similarity check — the inverse of this check is the "hold" rule below |

---

## 4. Design

### 4.1 Stable region identity (prerequisite for everything else)

Mint a region id **once** and carry it across compiles. Node ids stop
encoding membership.

- New table `regions` (or reuse `cluster_tree_nodes` with a `stable_id`
  column): `stable_id`, `parent_stable_id`, `container_path`, `centroid`
  (float32 blob), `member_count`, `created_run_id`, `last_full_recluster_run_id`.
- On a full re-cluster, match new HDBSCAN clusters to existing stable ids by
  **member overlap** (same Jaccard machinery as the note cache). Above a
  threshold → inherit the stable id; below → mint a new one; unmatched old
  ids → retired (kept for history, not drawn).
- Tag ids, region ids, layout seeds, compiled-note keys, and
  `region_assignments` on chunks all switch to the stable id.
- `_compile_cache_key` keeps its exact semantics; it just receives a stable
  id, so an unchanged region hits its exact key even after churn.

### 4.2 Incremental assignment: assign / hold / promote

Daily harvest path. Runs instead of HDBSCAN when the corpus delta is small.

1. **Load only changed documents** (A3). Drive `TerrainReader.load` from
   `get_last_compile_time()` the same way `/api/changes` already does.
   Unchanged chunks are read back from `chunks` + `embeddings` tables, not
   re-chunked. Deleted/archived docs are removed from their regions.
2. **Assign.** For each new chunk, score against the centroids of leaf
   regions *within its container* (global if no containers). If best cosine
   ≥ `ASSIGN_THRESHOLD` (start at 0.55, matching `CANDIDATE_THRESHOLD` in the
   merger), join that leaf. Update the centroid incrementally. Map does not
   move.
3. **Hold.** Otherwise the chunk goes into a per-container **pending pool**
   (`pending_chunks` table: chunk_id, container_path, best_region, best_sim,
   held_since_run). It is still indexed for the chatbot and still appears in
   the graph view; on the map it renders as an unplaced marker at the edge of
   `best_region` (frontend task, §6).
4. **Promote.** After assignment, run HDBSCAN over each pending pool alone.
   Any cluster with ≥ `min_cluster_size` chunks and mean pairwise cosine
   above the existing recursion threshold becomes a **new leaf region** with
   a fresh stable id, a layout seed placed adjacent to its nearest existing
   region, and a compile-report line ("New region: *X* — 14 notes"). Chunks
   left over stay pending.
5. **Age out.** A chunk pending for more than N runs is force-assigned to
   `best_region` so nothing floats forever. N configurable; start at 10.

### 4.3 Scheduled full re-cluster

Assign-only drifts: centroids move, siblings grow into each other, a region
that should have split never does. A full HDBSCAN run resets that.

Trigger when **any** of:
- new + changed chunks since the last full re-cluster exceed
  `FULL_RECLUSTER_FRACTION` of the corpus (start at 0.15);
- the pending pool exceeds a fixed size;
- a wall-clock interval has passed (weekly);
- the user asks (`--fresh` already exists; add `--recluster` that keeps caches
  but rebuilds the tree).

The full run goes through §4.1 matching so stable ids and layout seeds
survive. The compile report shows a diff: regions kept / renamed / split /
merged / new / retired, so a moving map is always *explained*.

### 4.4 What the user sees

- Daily: identical map, new notes inside existing regions, spires grow, maybe
  a few unplaced markers at region edges.
- Occasionally: a "new region" animation + report line.
- Weekly: possibly a small re-tile, with a diff in the compile report.

---

## 5. Task list

Ordered. Each item should be one PR.

- [ ] **5.1 Stable ids — store + matching.** `regions` table, overlap
      matcher, migration that assigns stable ids to the current tree from
      the last completed run's `cluster_tree_nodes`. *medium.*
- [ ] **5.2 Stable ids — compiler wiring.** Tags, regions, layout seeds,
      note cache keys, `region_assignments` use stable ids. Regression test:
      compile twice with one added doc → every pre-existing region keeps its
      id and position. *medium.*
- [ ] **5.3 Region-merger cache.** Key pair verdicts on `(a_stable_id,
      b_stable_id, prompt_version, centroid-sim bucket)`. Cheap win, remove
      up to 40 LLM calls/compile. *small.*
- [ ] **5.4 Incremental load.** `TerrainReader.load(since=...)`; read
      unchanged chunks from the store; handle deletions. Gate behind a flag
      until 5.5 lands (partial input is unsafe with full re-clustering).
      *medium.*
- [ ] **5.5 Assign / hold / promote.** New `IncrementalAssigner` in
      `utils/`; pending pool table; promotion via pooled HDBSCAN; age-out.
      Unit tests with synthetic embeddings for each branch. *large.*
- [ ] **5.6 Re-cluster trigger + diff.** Fraction / pool-size / interval
      triggers; region diff in the compile report; `--recluster` CLI flag.
      *medium.*
- [ ] **5.7 Frontend: pending markers + new-region reveal.** Render
      unplaced chunks at region edges; highlight newly promoted regions;
      show the region diff on `/compile`. *medium.*
- [ ] **5.8 Region cache key decoupling.** Stop embedding child-note
      previews in the region *key* (keep them in the prompt); key on child
      stable ids + child note cache keys instead. *small.*
- [ ] **5.9 Observability.** Per-compile counters: notes exact-hit /
      fuzzy-hit / synthesized, chunks assigned / held / promoted, LLM calls
      by stage. Surface in the compile report so cost regressions are
      visible. *small.*

---

## 6. Open questions

- **Threshold calibration.** 0.55 is borrowed from the merger. Needs a
  measurement on the 1,746-doc corpus: distribution of best-centroid cosine
  for chunks HDBSCAN placed vs. marked noise. Pick the threshold from that,
  not from intuition.
- **Multi-region membership.** `assign_multi_region` lets a chunk belong to
  several top-level regions. Does a pending chunk get secondary assignments,
  or only after promotion/force-assign?
- **Containers vs. semantics.** With folder-seeded clustering the backbone is
  the folder tree. Should a promoted region ever live outside its container?
  Proposal: no — promotion is always inside a container; cross-container
  structure only changes on a full re-cluster.
- **Retired regions.** Keep drawing a retired region greyed-out for one run so
  the user sees it go, or drop it immediately?
- **Layout for promoted regions.** "Adjacent to nearest existing region" needs
  a concrete rule in `layout.py` that does not push neighbours around.
- **Chunk id stability.** Chunk ids change when content changes. That is
  correct for caching but means a heavily edited page "leaves and re-enters"
  its region. Acceptable, or should assignment be keyed on `(doc_id, index)`
  with content hash tracked separately?

---

## 7. Acceptance criteria for v2

1. Adding ≤ 5 % new documents and recompiling produces a map where every
   pre-existing region has the same id, name, and position.
2. The same compile synthesizes notes only for regions/tags whose membership
   actually changed beyond the overlap threshold. Target: < 5 % of notes.
3. Ten documents on a genuinely new topic, added over several harvests,
   appear as a new region without the user running anything special.
4. A full re-cluster keeps ≥ 90 % of stable ids on an unchanged corpus.
5. The compile report explains every visible change to the map.
