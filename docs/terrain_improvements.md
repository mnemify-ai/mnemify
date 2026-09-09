# Terrain AI — Improvement Plan (v0.5)

## What we're doing and why

Today the terrain pipeline does three things well: it reads notes from your connected sources, breaks them into chunks, and groups those chunks into a brain map of regions and tags. That's a strong foundation, but three gaps are blocking the next phase of the product:

1. **The pipeline assumes long, well-structured documents.** Real corpora are messier — Notion sub-pages, Obsidian notes full of wikilinks, header-only outlines, sparse tasks. When the input doesn't match the assumption, structural context gets stripped away before the LLM sees it, and the resulting tags are weaker than they should be.

2. **There's nothing readable per tag or region.** Every tag has a `blurb` field, but it's always empty. Every region has a `summary` that's only used inside the brain map UI. Nothing in our output tells you, in plain language, what your knowledge actually says about a topic.

3. **There's no chatbot.** The brain map is the product today; you can navigate it visually but you can't ask it questions. To make the brain consumable by a chatbot we need: synthesized summaries to retrieve over, a flat graph the chatbot can traverse, and an `/ask` endpoint that streams answers grounded in your notes.

The outcome of this plan is a v0.5 release where the chunking and structural-context handling get noticeably better for fragmented sources; every region and every meaningful tag has a real synthesized description; entities like Alice and Project Phoenix get promoted to first-class graph nodes; the graph carries confidence labels explaining *why* two things are connected; and a working chatbot streams answers with citations grounded in the compiled brain.

---

## Before and after, in one sentence

**Today:** "A visual map of your knowledge clusters."

**After v0.5:** "A visual map *plus* a chatbot that knows the entities, themes, and your personal context — and shows its work with confidence labels and citations."

---

## What's out of scope

- **MarkItDown attachment ingestion** (PDFs, DOCX, XLSX, images). Originally proposed as Pillar 2 of the earlier terrain improvements doc. Deferred — the host doc continues to fall back to today's `[label](url)` behavior for attachments.
- **Incremental graph updates.** We rebuild the whole brain on every compile. Content-hash caching (Stage 3) means re-compiles cost almost nothing in LLM calls, so this isn't yet a user-blocking gap. LightRAG/Graphiti both support incremental ingest; we'd revisit in v0.6.
- **Temporal fact validity windows.** Graphiti's signature feature ("Kendra liked Adidas as of March 2026"). Defer until we hear users actually need point-in-time queries.
- **Permissions as first-class graph entities.** Irrelevant until we sell into teams/enterprise.
- **Communication-style profiles** (Glean Personal Graph). Not enough user data to be meaningful yet.
- **Sequence model over user interactions** (originally floated as "LSTM"). Defer to v0.6, after Stage 6 gathers real usage data. When we add it, prefer a small Transformer over an LSTM — Transformers dominate session-based recommendation in 2026.

---

## How we got here — research that shaped this plan

Before locking the stages, we evaluated the open-source landscape and Glean's product line as the head of AI would.

**The systems we studied:**

- **Microsoft GraphRAG** — canonical entity-graph RAG. Extracts entities + relationships, runs Leiden community detection, generates community summaries, supports local vs global query modes.
- **LightRAG** (HKUDS, 36k stars, EMNLP 2025) — simpler/faster GraphRAG. Hybrid storage (Neo4j + vector DB). Single-LLM-call extraction. Incremental updates.
- **Graphiti** (Zep, 27k stars) — temporal-first graph with bi-temporal fact validity windows. Hybrid retrieval (embeddings + BM25 + graph traversal).
- **safishamsi/graphify** (58k stars, MIT) — codebase-to-graph CLI. Tree-sitter AST extraction, Leiden communities, confidence-tagged edges, MCP server, shortest-path queries.
- **Glean Enterprise + Personal Graph** — graph-scoped hybrid retrieval, three-signal rerank (semantic + classical IR + graph signals), Personal Graph as a behavior-derived layer.
- **Obsidian-focused PKG repos** (MegaMem, second-brain, claude-obsidian, ODIN) — closer in domain to us; mostly variants of Karpathy's LLM Wiki pattern.

**Should we wholesale-adopt graphify or LightRAG? No.** Both are oriented around a different center of gravity (codebase AST for graphify, generic text RAG for LightRAG). Adopting either means losing what makes terrain *terrain* — the hex layout, multi-region weighted membership, recursive HDBSCAN with coherence stopping. The right play is to **cherry-pick the patterns each system gets right and graft them into our existing pipeline**.

**The patterns we are adopting:**

| From | Pattern | Lives in |
|---|---|---|
| graphify | Confidence-tagged edges (`extracted` / `inferred` / `ambiguous`) | Stage 4 |
| graphify | Leiden community detection as a complementary signal | Stage 4 |
| graphify | Shortest-path reasoning endpoint | Stage 7 |
| graphify | "Surprising connections" ranking | Stage 4 + 7 |
| GraphRAG / LightRAG | **Entities as first-class graph nodes** | Stage 4.5 |
| LightRAG / GraphRAG | Community-level summaries (region summaries get note-aware) | Stage 3 |
| Glean | Graph-scoped hybrid retrieval | Stage 5 |
| Glean | Three/four-signal rerank | Stage 5 |
| Glean | Lightweight personal-graph layer | Stage 6 |
| Modern GNN literature | GraphSAGE neighborhood embeddings (not LSTM) | Stage 4.6 |

---

## The plan, stage by stage

Each stage is **additive on the data side**. No breaking changes to `render-data.json`. The existing brain map renders identically throughout.

The stages are sequenced so each later one benefits from the prior. You can ship them in order and stop at any stage with a still-coherent product.

---

### Stage 1 — Source-aware chunking

**What it does.** Replaces the single hard-coded markdown chunker with a dispatcher that picks the right strategy per source type.

**Why it matters.** Today every source — Notion, Obsidian, Confluence, Jira, Gmail — gets chunked the same way. A Notion sub-page bleeds into its parent. Obsidian frontmatter ends up in chunk bodies. Confluence tables get shredded. The fix isn't smarter prompting; it's respecting how each source actually structures information.

**How.**

1. Introduce a `ChunkerRegistry` that maps `source_type` to a chunking strategy.
2. Default strategy = today's `MarkdownChunker` behavior — unregistered sources keep working unchanged.
3. Build tuned strategies for the three live sources:
   - **Notion** — respect `child_page`, `toggle`, `callout` block walls; pull `properties` (status, assignees, dates) into structured fields.
   - **Obsidian** — frontmatter becomes a chunk-zero context block, not body content; headings are primary splits; `--- ` thematic breaks are respected; wikilink anchors stay intact across merges.
   - **Confluence** — heading-based with table-aware splits (never shred a table).
4. In `compiler.py`, replace the direct `MarkdownChunker(...)` instantiation with `ChunkerRegistry.dispatch(doc)`.

**Files touched.**

- `backend/src/terrain/utils/chunker.py` — extract current logic into `chunkers/markdown_default.py`.
- `backend/src/terrain/chunkers/` (new) — registry + Notion, Obsidian, Confluence modules.
- `backend/src/terrain/pipelines/compiler.py` — swap chunker call.

**Verify.** Pick a Notion doc with sub-pages and an Obsidian note with frontmatter + wikilinks. Run `--stop-at chunk`. Confirm sub-pages produce separate chunks and frontmatter lands in `frontmatter_tags`, not chunk content.

---

### Stage 2 — Preserve structural context

**What it does.** Stops throwing away signal between chunking and the LLM. Captures the cross-references and hierarchy that already live in the data but never reach the model.

**Why it matters.** When the LLM sees a chunk in isolation, it has to guess what it's about. When it sees the chunk plus its heading path, parent doc title, wikilinks, and mentions, the extracted features get sharper. The same goes for embeddings — two notes both linking `[[Project Phoenix]]` should pull toward each other, but they don't if the wikilinks aren't part of the embedding text.

**How.**

1. **Fix `_merge_tiny`.** Today it keeps only the first chunk's heading_path; accumulate the union (preserving order) so headings aren't dropped during merging.
2. **Extract references into structured fields** on `TerrainChunk`:
   - `wikilinks` — Obsidian `[[Page]]` and Notion mentions
   - `urls` — outbound URLs, deduped
   - `mentions` — @people, Notion user mentions, Jira keys
   - `frontmatter_tags` — YAML frontmatter `tags:`
   - `source_properties` — Notion props, Jira status, per-source metadata bag
3. **Enrich the LLM prompt.** The extractor now sees a "Structural Context" block (parent doc, heading path, wikilinks, mentions, source properties) before the chunk content.
4. **Enrich the embedding text.** Append heading path and wikilinks so reference-linked chunks pull closer in embedding space.
5. **Soft reference-affinity in clustering.** In the HDBSCAN noise re-attachment and multi-region assignment, switch from pure cosine to a blended score: `0.7 × cosine + 0.3 × jaccard(references)`. Sparse notes that share `[[Project Phoenix]]` now cluster together even when embeddings are weak.

**Files touched.**

- `backend/src/terrain/utils/models.py` — extend `TerrainChunk` (all fields default-empty, so existing data still loads).
- `backend/src/terrain/utils/chunker.py` + per-source strategies — populate the new fields.
- `backend/src/terrain/agents/openai_clients.py` — extended prompt.
- `backend/src/terrain/utils/embedder.py` — extend `embedding_text()`.
- `backend/src/terrain/utils/clusterer.py` — blended affinity.

**Verify.** Confirm new fields populate. Spot-check that two sparse notes sharing a wikilink cluster together when they wouldn't have without it.

---

### Stage 3 — Compiled notes per tag and per region

**What it does.** Every region and every important tag gets an LLM-synthesized summary stored on the model. These become the retrievable units for the chatbot.

**Why it matters.** Right now `Tag.blurb` is always None. The brain map shows you the tag but can't tell you what your notes actually say about it. Worse, the chatbot in Stage 5 needs something coherent to retrieve over — chunk-level summaries are too fragmented.

**How.**

1. **Per region** (`TreeNode.summary`). We already call `OpenAIClusterNamer.name_region()`. Extend its prompt to include the synthesized blurbs of child tags (added below), not just chunk excerpts. Summaries become coherent across the region instead of being a mosaic of chunks.
2. **Per tag** (`Tag.blurb`).
   - **Eligibility:** `frequency ≥ 3` AND tag is in the top 15 by composite score (`frequency × log(1 + degree) × recencyScore`). Top-N held at 15 deliberately — keeps LLM cost reasonable.
   - **Eligible tags:** one LLM call each. Input = each member note's `Note.excerpt` plus the highest-confidence `ChunkFeatures.summary` per member. Output = 2–3 paragraph synthesis.
   - **Long-tail tags** (below threshold): extractive fallback — concatenate the truncated `ChunkFeatures.summary` of each member chunk (max ~400 chars). Stored on a separate field `Tag.blurb_extractive`, **not** `Tag.blurb`. The frontend renders the tag detail panel only when `Tag.blurb` is non-null. The extractive fallback is retrieval-only.
3. **Content-hash caching** — default behavior, not a flag.
   - Cache key = `sha256(prompt_version + sorted(member_content_hashes))`.
   - Cache lives at `.mnemify/cache/compiled_notes/{cache_key}.json`.
   - Bump `prompt_version` to invalidate everything in one go.
4. **Embed every compiled note.** After synthesis, embed via the same `EmbeddingClient` used for chunks. Store on the node. Without this, the chatbot can't do similarity search over the summaries.

**Files touched.**

- `backend/src/terrain/agents/openai_clients.py` — new `compile_tag_blurb(tag, members)`; updated `name_region`.
- `backend/src/terrain/pipelines/compiler.py` — new `_compile_summaries(brainmap)` stage between Derive and Validate.
- `backend/src/terrain/utils/models.py` — add `embedding` and `blurb_extractive` to `Tag`; `embedding` to `TreeNode`.
- `frontend/web/src/brainMap/types.ts` + tag detail panel — render blurb section only when `tag.blurb` is a non-empty string.

**Verify.** Run a full compile. Inspect `terrain.json`: every region has a non-trivial `summary`; top-15 tags have LLM `blurb`; long-tail tags have `blurb_extractive` but `blurb is None`; the UI panel suppresses the blurb section for null blurbs. Re-run compile with no source changes and confirm cache hit (no new LLM calls).

---

### Stage 4 — Graph emission with confidence labels and Leiden communities

**What it does.** Adds a flat, chatbot-traversable graph view to `terrain.json`. Tags every edge with **why** it exists (provenance + confidence). Runs Leiden community detection alongside HDBSCAN as a complementary clustering signal. Pre-computes a "surprising connections" feed.

**Why it matters.** Today our edges are pure numbers. The chatbot can't distinguish "Alice and Phoenix are connected because someone explicitly wrote `[[Project Phoenix]]` in Alice's bio" from "Alice and Phoenix are connected because the LLM guessed it." Trust requires legibility — the chatbot needs to be able to say which is which.

Leiden complements HDBSCAN: HDBSCAN is density-based (dumps sparse items into noise), Leiden operates on the graph itself and catches tight communities HDBSCAN misses. We use Leiden as a *soft signal* — HDBSCAN remains authoritative for the hex layout.

**How.**

1. Extend `BrainMap` with an optional top-level `graph: GraphView` field. The frontend rendering pipeline ignores it; chatbot retrieval uses it.
2. `GraphView` contains:
   - `nodes` — flat list. Each: `id`, `type ∈ {region, tag, note}`, `label`, `summary`, `embedding`, `homeRegionId`, `leidenCommunityId`, `centrality`.
   - `edges` — typed (`contains`, `co-occurs`, `linked-to`, `region-rel`, `belongs-to`), each carrying:
     - `weight: float`
     - **`provenance: "extracted" | "inferred" | "ambiguous"`** — `extracted` for explicit references (wikilinks, mentions); `inferred` for LLM- or cosine-derived; `ambiguous` for mixed.
     - **`confidence: float`** — 1.0 for extracted; `weight × source_confidence` for inferred; 0.4–0.6 for ambiguous.
   - `surprisingConnections` — top-20 edges ranked by `weight / (deg(from) × deg(to))`. Surfaces non-obvious cross-region links. Feeds the Daily Briefing card.
3. **Leiden pass.** New helper using `python-igraph` + `leidenalg` (small pip-installable deps). Assign every node a `leidenCommunityId`. As a soft signal, bump edge weights by +0.1 when both endpoints share a Leiden community.
4. **v3 bake strip.** In `_bake_v3.py`, do not propagate `graph`, `embedding`, or compiled-note text into `render-data.json`. They stay in `terrain.json` only.

**Files touched.**

- `backend/src/terrain/utils/models.py` — `GraphNode`, `GraphEdge`, `SurprisingEdge`, `GraphView`; add `graph` to `BrainMap`.
- `backend/src/terrain/pipelines/compiler.py` — `_build_graph_view`, `_run_leiden`, `_score_surprising`.
- `backend/src/terrain/_bake_v3.py` — confirm field exclusion.
- `pyproject.toml` — add `python-igraph`, `leidenalg`.

**Verify.** Open `terrain.json`. Confirm `graph.nodes` and `graph.edges` exist; every edge has `provenance` and `confidence`; `surprisingConnections` is populated; nodes have `leidenCommunityId`. Confirm `render-data.json` shape is unchanged.

---

### Stage 4.5 — Entity promotion and the layered graph (the biggest leap)

**What it does.** Brings entities — Alice, Project Phoenix, the Stripe API, OCR accuracy — up as first-class graph nodes alongside tags and regions. Organizes the whole graph into four explicit layers with cross-layer edges.

**Why it matters.** This is the biggest structural improvement in the plan. Today our tags are *topics* (named clusters of chunks). The actual things people mention across notes — people, products, projects — are buried inside chunk content and never promoted. The chatbot can't directly answer "what do we know about Alice?" — it has to find a topic cluster that happens to contain her.

After this stage, Alice gets her own node, her own LLM-written summary, and explicit edges to (a) the notes that mention her, (b) the tags she belongs to, and (c) other entities she co-occurs with. The chatbot can take multiple semantic paths to the same answer and triangulate.

**The layered structure.**

```
Layer 3:  Regions   ──┐         (themes — super-clusters of tags)
                      │  belongs_to_theme
Layer 2:  Tags    ────┘
                      │  mentioned_in
Layer 1:  Entities ───┤         (NEW)
                      │  mentions
Layer 0:  Notes  ─────┘         (already exists in mocknotes)
```

- **Within-layer edges:** `entity↔entity` (co-mention), `tag↔tag` (existing tagEdges), `region↔region` (existing regionEdges).
- **Cross-layer edges:** `note→entity` (mentions), `note→tag` (already exists via `primaryTagId`/`tagIds`), `entity→tag` (belongs_to_theme), `tag→region` (already exists).

**How.**

1. **Aggregate the entity signal.** Most of it already exists: `ChunkFeatures.entities`, `ChunkFeatures.products`, `ChunkFeatures.customers`, plus Stage 2's `TerrainChunk.mentions` and `TerrainChunk.wikilinks`. Aggregate per `(label, type)` across the corpus. Type ∈ `{person, product, project, customer, concept}`.
2. **Eligibility.** Keep entities with ≥3 distinct notes AND in the top 30 by mention frequency. Same shape as the Stage 3 tag rule.
3. **Canonicalize labels.** Lowercase, strip punctuation, fuzzy-merge variants. ("Project Phoenix", "phoenix project", "Phoenix" → one node.) Use `rapidfuzz` if available, otherwise difflib `SequenceMatcher` ≥ 0.85.
4. **Per-entity compiled note** (LLM, one call each, gated by eligibility). Summary, role/description, key relationships. Same caching pattern as Stage 3.
5. **Per-entity embedding** via the same `EmbeddingClient`.
6. **Long-tail entities** (below threshold): extractive fallback (concat first occurrences) on `Entity.blurb_extractive`. Frontend renders entity panel only when `Entity.blurb` is LLM-synthesized.
7. **Build the cross-layer edges** — all derived from existing data, no LLM calls.
   - `note→entity`: emit `mentions` from each note to every entity whose label appears in any of its chunks.
   - `entity→tag`: emit `belongs_to_theme` with weight = `|notes_mentioning_entity ∩ tag.noteIds| / |tag.noteIds|` for pairs where weight ≥ 0.3.
   - `entity↔entity`: emit co-mention with weight = `|shared_notes| / min(|notes(e1)|, |notes(e2)|)` ≥ 0.2.
8. **Extend `GraphView`.** Add entity nodes (`type="entity"`, `entityType` field). Add `mentions`, `belongs_to_theme` to the edge type enum.

**Files touched.**

- `backend/src/terrain/utils/models.py` — new `Entity` model (parallel to `Tag`); extend `GraphView`.
- `backend/src/terrain/pipelines/compiler.py` — new `_promote_entities(chunks, brainmap)` helper, called between `_compile_summaries` (Stage 3) and `_build_graph_view` (Stage 4).
- `backend/src/terrain/agents/openai_clients.py` — new `compile_entity_blurb(entity, members)`.
- `backend/src/terrain/utils/canonicalize.py` (new, small) — entity label normalization + fuzzy merge.

**Verify.** Inspect `terrain.json`. Confirm entity nodes exist with `entityType`. Pick a known entity (e.g., "Project Phoenix") and verify: (a) it has an LLM-synthesized `blurb`, (b) `mentioned_in` edges to its notes, (c) `belongs_to_theme` edges to overlapping tags, (d) `entity↔entity` co-mention edges with reasonable weights, (e) canonicalization merged variants.

---

### Stage 4.6 — GraphSAGE neighborhood embeddings

**What it does.** Every node gets a second embedding — `context_embedding` — that absorbs information from its graph neighbors via a single GraphSAGE pass. The chatbot blends both (`0.7 × context + 0.3 × raw`) for similarity search.

**Why it matters.** Today a node's embedding is purely its own text. Two tags both labeled "Launch" — one for marketing, one for engineering — get nearly identical embeddings even though their neighborhoods are completely different. After this stage, each embedding is context-aware. Search finds nodes similar *in context*, not just similar *in name*.

**About LSTM.** This is the "more than cosine" upgrade. LSTM was floated as the mechanism. Honest take: in 2026, graph message-passing networks (GraphSAGE / GAT / R-GCN) have superseded LSTM for this exact job. We're using the modern equivalent. A small sequence model (Transformer, not LSTM) may make sense in v0.6 for predicting *next-action* from user session history, but that's a different problem from "make node embeddings neighborhood-aware."

**How.**

1. After Stage 4.5 populates the layered graph, build a homogeneous undirected version of `GraphView` for the GraphSAGE pass. Edges weighted by `weight × confidence`. All four node types as nodes; cross-layer and within-layer edges treated uniformly for message passing.
2. Run a single GraphSAGE forward pass:
   - Input features per node = the text embedding from Stage 3 (1536-dim for `text-embedding-3-small`).
   - 2 GraphSAGE layers with mean-aggregator + ReLU between them.
   - Output dim = same 1536 (so blending is straightforward).
   - **v0.5 ships without training** — use the GraphSAGE forward as an unsupervised neighborhood mixer with fixed random weights, OR fall back to a deterministic mean-of-neighbors baseline.
3. Store as `GraphNode.context_embedding`. Keep raw `embedding` intact so the chatbot rerank can blend both.
4. Cache by `hash(prompt_version + graph_topology_hash)` — recompute only when graph changes.

**Default for v0.5: ship the mean-of-neighbors baseline.** It's 30 lines, no heavy dependency, and gets ~80% of the benefit. Upgrade to true GraphSAGE in v0.6 if Stage 5 retrieval quality measurements justify the `torch-geometric` dependency. The plan emits `context_embedding` either way, so the upgrade is non-breaking.

**Files touched.**

- `pyproject.toml` — `torch` + `torch-geometric` if going full GraphSAGE; nothing if going mean-of-neighbors.
- `backend/src/terrain/utils/graph_embed.py` (new) — `compute_context_embeddings(graph_view)`.
- `backend/src/terrain/pipelines/compiler.py` — call after `_build_graph_view`.
- `backend/src/terrain/utils/models.py` — add `context_embedding` to `GraphNode`.

**Verify.** Pick two tag nodes with similar labels but different neighborhoods. Confirm their raw embeddings are close (cosine > 0.85) but `context_embedding` vectors diverge (cosine drops by ≥ 0.05).

---

### Stage 5 — The chatbot: `/ask` endpoint with hybrid graph-scoped retrieval

**What it does.** A real chatbot endpoint that takes a question, retrieves grounded context from the layered graph, and streams an answer back via SSE. The user brings their own Anthropic or OpenAI key.

**Why it matters.** This is the user-facing payoff of all the earlier stages. The retrieval algorithm is Glean-style: graph narrows the search space, vector similarity finds the best candidates inside it, multi-signal rerank picks the top context bundle. Citations show provenance, so the user knows when the chatbot is on firm ground vs. extrapolating.

**Backend.**

- **Route.** `POST /api/ask`. Body: `{query, provider, model, history?}`. API key via `Authorization: Bearer <key>` header. Never logged.
- **Retrieval algorithm — step by step:**
  1. **Query understanding** (one cheap LLM call). Extract from query: target node types, explicit mentions, topic intent, time scope.
  2. **Parallel seeding in both layers.**
     - Entity-layer seeds: entity nodes matching mentions (case-insensitive substring + fuzzy ≥ 0.85).
     - Tag/region-layer seeds: top-5 tag nodes by cosine of topic-intent embedding against `tag.context_embedding`.
  3. **Within-layer 1-hop walk** for each seed via edges with `weight ≥ 0.4` AND `confidence ≥ 0.6`. Cap ±5 neighbors per seed.
  4. **Cross-layer walk** for top-3 seeds in each layer.
     - From entity seeds → follow `belongs_to_theme` into tags → pick up other entities in those tags.
     - From tag seeds → follow `mentions` into entities → pick up other tags those entities appear in.
  5. **Candidate pool** = within-layer ∪ cross-layer. Cap at ~40.
  6. **Four-signal rerank:**
     ```
     score = 0.55 · cosine(query, 0.7·context_embedding + 0.3·embedding)
           + 0.15 · recencyScore
           + 0.10 · degree / max_degree
           + 0.20 · userAffinity      // Stage 6 — defaults to 0 if usage log absent
     ```
     Top-15 after rerank.
  7. **Context bundle.** Ordered list of `{label, summary, type, layer, citation_id, edge_provenance_to_neighbor}`. Cap to ~6k tokens (truncate lowest-scored first). Include both entity-layer and theme-layer hits so the LLM can triangulate.
  8. **System prompt** tells the LLM: "Answer only from this context bundle. Cite nodes by `[citation_id]`. If an edge is inferred or ambiguous, acknowledge uncertainty. Prefer points where entity-layer and theme-layer evidence agree."
  9. **Stream via SSE.**
- **Provider abstraction.** `stream_chat(provider, model, key, messages) -> AsyncIterator[str]`. Anthropic Messages streaming + OpenAI Chat Completions streaming.

**Frontend.**

- New "Ask" tab inside the existing `SideDrawer.tsx`.
- Chat input + message list.
- **Citation chips** on assistant messages. Clicking selects the corresponding tag/region in the brain-map store and highlights it on the 3D map.
- **Provenance badges** on citations — solid for `extracted`, outline for `inferred`, dashed for `ambiguous`. Surfaces edge confidence to the user.
- Settings panel: provider radio (Anthropic / OpenAI), model picker, API key input. Persist to `localStorage` under `mnemify.ask.{provider}_key`. Never sent anywhere except the `/api/ask` request.

**Files touched.**

- Backend: `backend/src/api/routes/ask.py`, `backend/src/api/retrieval.py`, `backend/src/api/providers/` (Anthropic, OpenAI streaming).
- Frontend: extend `SideDrawer.tsx`; new `frontend/web/src/ask/` (`AskTab.tsx`, `MessageList.tsx`, `CitationChip.tsx`, `SettingsPanel.tsx`); hook into `brainMap/store.ts` for citation→selection.

**Verify.** Curl test with a real key returns an SSE-streamed answer. UI Ask tab streams the same answer with citation chips and provenance badges. Clicking a chip highlights the right node on the 3D map.

---

### Stage 5.5 — General entity identification (retire the product special-case)

**What it does.** Replaces the seeded `KNOWN_PRODUCTS` mechanism with general, salience-ranked, typed entity extraction. Products stop being a special case — they become one entity type among many (`person`, `organization`, `product`, `project`, `topic`, `concept`, …). Every extracted entity carries a **salience** score, and corpus-level importance becomes `frequency × mean(salience) × spread` (distinct regions/tags the entity touches) instead of raw mention count.

**Why it matters.** The entity layer already promotes people/customers/concepts, but `product` typing depends on a hardcoded list that biases every non-founder corpus, and there's no `organization` or `topic` type at all. After this stage the brain is corpus-agnostic: "what do we know about X?" works whether X is a person, a company, or an educational topic — the precondition for any non-founder user. The product list is demoted to an *optional prior* (Stage 5.6), never a requirement.

**How.**
1. Generalize the extractor schema: replace the `products` / `customers` / `entities` trichotomy with a single typed span list `entities: [{label, type, salience}]`. Keep `products` / `customers` as derived views for backward compatibility.
2. Rewrite the extractor system prompt + `_prompt` for typed NER with salience, grounded to spans present in the chunk (no invented entities). Drop the "from the provided list" scoping on products.
3. Add `organization` and `topic` to the taxonomy; make it **per-workspace** (read from `mnemify.yaml`, same pattern as products) so non-SaaS domains can declare their own (`case`, `regulation`, …).
4. Extend `_promote_entities`: importance ranking by `frequency × salience × spread`; per-`(label)` majority-vote typing to suppress cross-chunk type drift.
5. Upgrade canonicalization (`canonicalize.py`): the current char-level difflib under-merges ("Project Phoenix" ≠ "phoenix project"). Move to token-set matching and/or embedding-cluster the candidate labels (reuse the existing embedder).
6. Bump `SCHEMA_VERSION` (one-time full re-extract).

**Guardrails.** Require the label to appear in chunk text; keep the ≥3-note eligibility gate; salience suppresses one-off noise. The config product/interest list is a *boost*, not a gate — a zero-config corpus still yields sensible typed entities.

**Status.** The config-driven product list and derive-from-prior resolution (`_resolve_products`, products in the feature cache key) are **already implemented** as the bridge step. This stage is the generalization beyond products.

**Files touched.**
- `backend/src/terrain/utils/models.py` — generalize `ChunkFeatures` / `OpenAIChunkFeatures` entity fields; extend the type enum.
- `backend/src/terrain/agents/openai_clients.py` — typed-NER prompt + salience; drop list scoping.
- `backend/src/terrain/pipelines/compiler.py` — `_promote_entities` ranking + majority-vote typing.
- `backend/src/terrain/utils/canonicalize.py` — token-set / embedding-based merge.
- `mnemify.yaml` — per-workspace entity taxonomy.

**Verify.** Compile a fresh non-founder corpus with no config: confirm sensible typed entities including organizations and topics, ranked by importance, with no spurious products. Confirm declared products/interests sharpen typing but aren't required for the layer to populate.

---

### Stage 5.6 — Interest recommendation & curation loop

**What it does.** Surfaces a system-generated outline of the corpus's candidate topics and entities for the user to confirm, edit, or extend before the brain is finalized. The curated list becomes the user's `interests` — an explicit prior that feeds extraction (Stage 5.5), retrieval (Stage 5), and affinity (Stage 6).

**Why it matters.** Users are bad at recalling their interests from a blank box and good at recognizing them in a list. Because the suggestions are derived from the user's *actual* harvested documents, this is a grounded, zero-hallucination answer to the cold-start problem — and it **supersedes the generative-product-bootstrap idea**, which was circular (a fresh corpus had nothing to derive products from, and asking an LLM to invent product names risked hallucination). Here the system proposes from real content; the human curates.

**How.**
1. **Outline source — reuse, don't re-read.** The candidate outline is the compile's own region/tag/entity layer, importance-ranked. For a cheap *pre-compile* preview, run a recon pass = a compile with `--stop-at derive` (cluster + name, skipping the expensive Stage 3–4.6 synthesis). Otherwise the first full compile's top entities/tags serve directly. No separate document-reader pipeline — that would duplicate extraction at ~2× cost.
2. **Curation UI.** Present ranked suggestions grouped by type; the user selects / edits / adds. Persist to `.mnemify/interests.json` (and/or `mnemify.yaml`).
3. **Feedback wiring.** Curated interests feed: (a) the Stage 5.5 extraction prior (modest boost — lower the eligibility threshold and add a small salience bonus for declared terms); (b) the Stage 5 retrieval rerank; (c) Stage 6 affinity as an explicit cold-start seed.
4. **Combine cleanly with Stage 6.** Declared interests (explicit, pre-compile) and behavioral `userAffinity` (learned, post-compile) are the same intent at two different times — combine them in the rerank without double-counting (e.g. `max`, not sum).

**Guardrails.** Interests are **optional** (the engine produces a useful brain with none) and **never auto-applied** (always user-confirmed). The boost stays **modest** — strong enough to sharpen, weak enough to preserve discovery and the surprising-connections feed. This dial is the one parameter to tune against a real corpus rather than pick by hand.

**Files touched.**
- `backend/src/terrain/pipelines/compiler.py` — recon `--stop-at derive` outline extraction; interest-prior application.
- `backend/src/api/` — new route to fetch suggestions + persist curation.
- `backend/src/terrain/utils/` — interests store (`.mnemify/interests.json`).
- `frontend/web/src/` — onboarding / curation panel (ranked suggestions grouped by type).

**Verify.** After a first compile (or recon pass), the UI shows ranked topic/entity suggestions grouped by type. Selecting some and recompiling boosts them modestly without suppressing organically-important entities. A user who selects nothing still gets a coherent brain.

---

### Stage 6 — Lightweight personal-graph layer

**What it does.** Logs which notes/tags/regions the user actually interacts with, derives a per-tag `userAffinity` score, plugs it into the Stage 5 rerank.

**Why it matters.** We currently know nothing about how each user uses their brain. Glean's whole Personal Graph is built on this. Our slice is simpler — interaction log + exp-decay scoring — but enough to make the chatbot feel like it knows what you're working on. All data stays local.

**How.**

1. **Frontend logging.** In `brainMap/store.ts`, fire a buffered event when the user:
   - Selects a tag on the 3D map (`tag_select`)
   - Opens a note from the side drawer (`note_open`)
   - Expands a region (`region_expand`)
   - Dwells > 5 seconds on a tag detail (`tag_dwell`)
2. **Backend ingest.** `POST /api/usage` appends one JSONL line to `.mnemify/usage.jsonl`: `{ts, action, targetId, dwellMs?}`. Append-only.
3. **Affinity derivation at compile time.** New `_compute_user_affinity(graph_view, usage_log)` in `compiler.py`:
   - Read last 30 days of `usage.jsonl`.
   - Per-tag affinity = exp-decay-weighted count: `tag_select` weight 1.0, `note_open` of a tagged note weight 0.5, `tag_dwell` weight 0.7 × `min(dwellMs/30000, 1.0)`.
   - Normalize to [0, 1]. Store as `GraphNode.userAffinity`.
4. **Wire into Stage 5 rerank** via the `w_personal` term (already in the scoring formula).

**Files touched.**

- `frontend/web/src/brainMap/store.ts` — event hooks.
- `frontend/web/src/usage/logger.ts` (new) — buffered POST.
- `backend/src/api/routes/usage.py` (new) — append-only handler.
- `backend/src/terrain/pipelines/compiler.py` — `_compute_user_affinity`.

**Privacy.** All usage data stays on the local `.mnemify/` directory. No external transmission. Call this out prominently in the README.

**Verify.** Click some tags in the UI. Confirm `.mnemify/usage.jsonl` grows. Re-run compile. Confirm `GraphNode.userAffinity` is non-zero for the clicked tags. Ask a vague chatbot question and verify the clicked tags rank higher than they did before.

---

### Stage 7 — Graph reasoning APIs

**What it does.** Exposes two endpoints that fall out for free from the work in Stages 4 and 4.5: shortest-path between two nodes, and the "surprising connections" feed.

**Why it matters.** Both unlock user-facing features cheaply.
- Shortest-path answers "how is X connected to Y?" — a common question the brain map can't answer today.
- Surprising connections feeds the Daily Briefing card already on the roadmap.

**How.**

1. `GET /api/graph/path?from={node_id}&to={node_id}&max_hops=4`
   - Dijkstra over `GraphView`. Edge cost = `1 - weight × confidence`.
   - Return ordered list of `{node, edge, provenance, confidence}`. 404 if no path within `max_hops`.
2. `GET /api/graph/surprising?limit=20`
   - Return the pre-computed `surprisingConnections` from Stage 4.
3. **Frontend "Connections" tab in SideDrawer.** Two-node picker → renders the shortest path as a chain of badges, color-coded by edge provenance.
4. **Daily Briefing card** consumes `/api/graph/surprising` for the "non-obvious links" row.

**Files touched.**

- `backend/src/api/routes/graph.py` (new).
- Extend `SideDrawer.tsx` with the Connections tab.
- `frontend/web/src/graph/PathView.tsx` (new).

**Verify.** Hit both endpoints with curl, confirm well-formed JSON. UI Connections tab renders a path with provenance-colored badges.

---

## Cross-cutting notes

- **All stages are additive.** No breaking changes to `render-data.json`. The existing brain map renders identically throughout.
- **Cost budget.** Stages 3 and 4.5 are the main LLM-cost increases. Per fresh compile, expect ~1 LLM call per region (~10–30) + ~15 per-tag synthesis calls + ~30 per-entity synthesis calls + the existing per-chunk extraction. Embeddings on summaries are cheap (`text-embedding-3-small`). GraphSAGE pass (Stage 4.6) is local CPU compute, runs in seconds.
- **Caching is default behavior.** Re-compiles with no source changes pay near-zero LLM cost.
- **Prompt versioning.** A `PROMPT_VERSION` constant lives at the top of `openai_clients.py`. Bump it whenever any prompt changes — this auto-invalidates the compiled-notes cache.

---

## Deferred to v0.6

Things we deliberately left out, with the trigger for picking them up:

| Deferred item | Pick up when |
|---|---|
| MarkItDown attachment ingestion | Users explicitly ask for PDF/DOCX content in the brain |
| Incremental graph updates | Real compiles start feeling slow despite caching |
| Temporal fact validity windows | Users ask point-in-time questions |
| Sequence model over user behavior | Stage 6 has gathered 4+ weeks of usage data |
| True GraphSAGE training (vs mean-of-neighbors baseline) | Stage 5 retrieval quality measurements justify the `torch-geometric` dep |
| MCP server output | After v0.5 ships and we want external Claude Desktop / Cursor integration |
| Permissions as graph entities | Enterprise / team rollout |
| Communication-style profiles | Enough user data + multi-user demand |

---

## Open questions to revisit before each stage

- **Stage 1:** Which Notion block types matter most? `child_page`, `toggle`, `callout` are the obvious ones — are there others worth special handling in v0.5?
- **Stage 3:** Top-15 tag eligibility threshold — should we measure this against real corpora and tune, or is the heuristic good enough to ship?
- **Stage 4.5:** Entity type taxonomy is `{person, product, project, customer, concept}` — is this the right v0.5 set? Adding `event` / `metric` later is non-breaking.
- **Stage 4.6:** Ship mean-of-neighbors baseline or invest in `torch-geometric` upfront? Default is baseline; revisit if Stage 5 quality demands more.
- **Stage 5:** Reranking weights (`0.55 / 0.15 / 0.10 / 0.20`) are picked by hand — should we tune them against a small eval set before shipping?

---

## TODO — follow-up work surfaced during v0.5 implementation

These items came out of code review and aren't part of any shipped stage. Resolved items are recorded under *Applied* for the record; the rest are pending, listed roughly in order of impact × inverse-effort.

### Applied (cleanup done during the v0.5 build)

- **Blended affinity in `assign_multi_region` only fires when both sides have refs.** The original `0.7·cosine + 0.3·jaccard` blend silently penalized dense-text chunks with no wikilinks/mentions by raising their effective threshold from 0.45 to ~0.64. Fix: if either `chunk_refs` or `root_refs` is empty, fall back to pure cosine; otherwise blend. Restores the pre-Stage-2 attach behavior on dense chunks while keeping the sparse-ref boost.
- **Tag eligibility for compiled notes uses `Tag.elevation`.** The original `_compile_summaries` recomputed `frequency × log1p(degree) × recencyScore` for ranking, but `_derive_tree` already emitted `Tag.elevation = round(100 × frequency × recency × max(1, degree) / max_global)` for the hex layout. Two formulas → two rankings → silent inconsistency. Fix: sort by `(-elevation, -frequency, id)`. "Top 15 by LLM eligibility" now means "top 15 spires on the hex map," consistent across the product.
- **Type-aware entity canonicalization.** The previous `_promote_entities` used a single `(label) → type` dictionary, picking the highest-priority type per label via the hardcoded `person > customer > product > project > concept` order. That collapsed "Stripe (customer)" and "Stripe (product)" into one node by accident. Fix: aggregate by `(label, type)` pairs; canonicalize labels *per type* via `fuzzy_canonical_map`; entity ids now incorporate the type so cross-type collisions stay as distinct nodes.
- **Leiden made functional.** `igraph` + `leidenalg` added to `pyproject.toml`; same-community edges get a `+0.1` weight bump (`LEIDEN_WEIGHT_BUMP`, applied after the surprising pass) so Leiden actually influences retrieval. Previously it emitted community ids that nothing consumed and the deps weren't even installed.
- **Recency wired into the rerank.** `GraphNode.recency` is now stamped from `Tag.recencyScore` at graph emission and consumed by the four-signal rerank — it was hardcoded to `0`, silently wasting 15% of the ranking signal.
- **Dynamic product vocabulary (parts 1–2).** `_resolve_products` reads `products:` from `mnemify.yaml` (folded into the feature cache key) and derives from the prior compile's product entities (best-effort, deliberately *not* cache-keyed to avoid re-compile thrash). Hardcoded `KNOWN_PRODUCTS` auto-injection removed. Generative discovery on a brand-new corpus → Stage 5.6.
- **LLM query understanding.** `/api/ask` runs a best-effort, provider-agnostic structured call (`{nodeTypes, mentions, topicIntent}`, 7s timeout) before retrieval, merged with the regex heuristic and falling back to it on any failure.
- **Notes are citable.** Note nodes inherit a discounted score from their best-connected tag/entity (`_note_semantic_score`), so source notes reach the bundle and get citation ids — they scored a flat `0` before. Backend only; the frontend `openDoc` chip wiring is still pending (below).
- **Surprising-connections min-degree gate.** Edges now require both endpoints to have degree ≥ `SURPRISING_MIN_DEGREE` (3) before they're eligible, killing rare-pair noise on small graphs.
- **Graph-emission & retrieval correctness.** Entity promotion now runs *before* Leiden + surprising (entities were excluded from both); the retrieval candidate cap is insertion-ordered with seeds first (it was truncating a `set` in arbitrary hash order, able to drop seeds); a dead no-op ternary in entity emission was removed.
- **Raw chunk expansion in `/api/ask` (v0.8).** The context bundle's note/signal items are expanded with raw source-chunk text from `terrain.db` (`ask_expansion.py`, ~24k-char budget, 3 chunks / 4k chars per item) — previously the LLM only ever saw 160-char note excerpts, so corpus detail was unreachable no matter how well retrieval ranked. This intentionally bends the old "the chatbot only sees `terrain.json`" invariant: the ask path now also *reads* `terrain.db` (still no new persistence). Note nodes are stamped with `sourceChunkIds` at emission; older artifacts resolve via the `n-{short_hash(doc_id, 8)}` mapping.
- **Cited-only chips (v0.8).** The answer's `[cN]` markers are parsed server-side and emitted as a `citations_used` SSE event after the stream; the frontend filters chips to cited items (live as markers stream in), falling back to the top-scored items labeled "related context" when a model cites nothing.
- **Retrieval hygiene (v0.8).** Regions are now reachable (cosine seeding + `contains` in the cross-layer allowlist); bundle items carry their rerank `score` with a `MIN_ITEM_SCORE` floor (min 3 items kept); the dead `W_PERSONAL` weight renormalizes away until Stage 6 lands; candidate-cap overflow keeps seeds and fills by semantic score; `understanding.nodeTypes` applies a small rerank boost; `understand_query` sees the last 2 turns so follow-ups embed the resolved topic; a query/graph embedding-dimension mismatch is now a hard 503 instead of a silently empty bundle.
- **Chunk-level semantic search (v0.8).** The compile stamps `chunks.embedding_hash` at the end of enrich (the hash isn't re-derivable at ask time — wikilinks/frontmatter aren't persisted), and `/api/ask` cosine-searches the raw chunk vectors (`ask_chunks.py`, cached numpy index by db mtime). Matched chunks seed their parent note nodes with real per-note semantic scores — previously sibling notes under one tag scored identically via inheritance and the right one was unfindable — and lead their note's expansion list. Requires one post-v0.8 compile to activate on existing corpora.
- **Lateral edge confidence floors (v0.8).** Per-edge-type confidence floors in retrieval (`linked-to`/`co-occurs`/`region-rel` → 0.45) — the compiler emits these at ≤0.5, so the uniform 0.6 gate had made every lateral tag↔tag connection unwalkable. The compile-side calibration question (below) stays open; this unblocks retrieval meanwhile.
- **Ask perf + eval (v0.8).** `terrain.json` is parsed once and cached by mtime instead of per-request; `scripts/ask_eval.py` runs a golden question set through the real retrieval stack (no chat LLM) so retrieval constants are tuned against measurements — see `docs/ASK_PIPELINE.md` §7.
- **Action items with deadlines (v0.8).** Todo signals now carry `due_text` (verbatim phrase) + `due_date` (ISO). The LLM extractor copies the phrase verbatim and never resolves relative dates (drafts are cached by content hash, so resolution must be wall-clock independent); `terrain/utils/deadlines.py` resolves them deterministically at grounding time against the doc's `_effective_modified` anchor. The regex tier resolves todo lines the same way. Overdue/≤7-day items get a compile-time severity bump (+25/+15 — a snapshot that goes stale); authoritative urgency buckets (overdue / due_soon / upcoming / no_date) are computed against *today* at read time by the new `GET /api/action-items`, surfaced on the frontend's `/action-items` page (dismissals in localStorage, keyed on stable signal ids). `SCHEMA_VERSION` bumped v4→v5, so the first post-upgrade compile re-extracts features.

- **Vanishing regions in the v3 bake (2026-09-02).** `voronoi_assign` warped hex positions but not the region centroids it measured against; locally the warp is a near-constant ~`warp_amp` displacement, so every disc shifted bodily relative to its own centre and the outer cutoff erased any region smaller than that shift. On a 23-region Confluence corpus 8 top-level regions (12% of chunks, incl. a 17-doc "Machine Learning") rendered zero hexes and the UI hid them; every other region kept only a fraction of its territory (land 778 hexes) and sat ~4.4 units off its label. Fix: warp the centroids with the same field (differential warp) — 0 lost regions, 36/36 tags, land ≈ 2100, drift 0.7, organic borders kept. `expand_squeezed_leaves` now seeds zero-hex leaves first (it could only grow from owned hexes before) and never pushes a leaf below its own tag count. Coverage counters (`regions`/`tags` rendered vs compiled, land hexes, per-region hexes) are logged on the compile stream, stored under `counts.render` in `terrain_runs`, and warned on when anything is dropped. `tests/test_bake_v3.py` pins the invariants; `scripts/bake_compare.py [--baseline] [--png]` produces before/after coverage + top-down renders. Details: `docs/terrain_render_pipeline.md` §6.
- **Sub-regions squeezed out by the nested split (2026-09-02).** The nested subdivision of a parent's territory was plain warped Voronoi on the children's centroids. The warp gradient at `warp_amp` 7 is up to ~1 unit per unit, larger than typical sibling spacing, so one child regularly took almost everything (a 30-note sub-region kept 1 hex, a 6-note sibling 181). Users saw it as "hover never activates a sub-region" and "drilling into a sub-region moves the panel/camera but not the highlight". `assign_hexes_to_leaves` now uses `balanced_subdivide` — a capacity-constrained power diagram (warped distance minus an adaptively adjusted per-child weight) that gives each child a tag-proportional share of the parent's hexes while keeping the organic borders. On the 23-region corpus every sub-region leaf owns 20–102 hexes in one connected block. `BALANCED_NESTED_SUBDIVISION` (module constant) restores the old split for `scripts/bake_compare.py --baseline`; `bake_compare` now lists per sub-region counts and flags any with ≤ 4 hexes. Tests in `tests/test_bake_v3.py`. Along with it `LAYOUT_FILL` went 0.35 → 0.50: the old value was tuned against the erased/shrunken footprints, and with true footprints the map read as islands scattered across an empty desk. On the reference corpus the land bounding box shrinks from 93×81 to 78×73 world units with every region and sub-region still rendered; revert the one constant if the tighter packing is unwanted.

- **Duplicate sibling region names (2026-09-02).** Three top-level regions plus one child were all named "Document Intelligence" (80 names, 75 distinct on one compile). Each theme/region was named by an independent LLM call with no sibling context and no uniqueness pass, and the theme prompt literally asked for an "umbrella category (e.g. 'Machine Learning')". Fix: a post-naming collision pass (`TerrainCompiler._resolve_name_collisions`) — siblings sharing a label (or a child sharing its parent's) are re-named through the normal `_name_jobs` path with `avoid_names` (the taken labels) in the prompt and in the cache key (`_fingerprint(..., extra=)`), largest region keeps the name, ≤2 rounds, then a deterministic defining-term suffix. Theme/region prompts now ask for a 2–4 word name specific enough to distinguish the theme within the workspace. This is labelling only — it never merges; whether two clusters are one topic stays the merger's content-based call. `_log_build_diagnostics` now also emits a warning on the compile stream if duplicates survive. Tests: `tests/test_terrain_name_collisions.py`.
- **Region-merger verdicts persisted (2026-09-02).** `RegionMerger.merge(..., on_verdict=)` reports every judged pair (similarity, decision, parent, reason, the heuristic labels the judge saw); the compiler logs each on the compile stream and stores them in the new `merger_verdicts` table (per run). Previously they existed only in stdout, so "why are these two still separate?" was unanswerable after the fact.
- **Threshold evaluation harness (2026-09-02).** `scripts/threshold_eval.py` — `pairs` (all top-level region pairs with raw / mean-centered / cross-chunk cosine + summaries + latest merger verdict as a weak label, for hand labelling), `score` (AUC + best threshold per metric, candidates admitted), `multi` (secondary-region assignments under the current 0.45 rule vs. a margin rule vs. a centered rule, for labelling), `layout` (raw vs centered MDS neighbour agreement). First run on the Confluence corpus: the current 0.55 merger threshold admits 137/253 pairs; the current multi-region rule gives 9.2 secondary regions per chunk; and — notably — MDS on *mean-centered* centroids agrees **worse** with chunk-level neighbours (7/23 vs 14/23 for the current raw layout), so centering is not the automatic improvement it looked like. **No threshold was changed**; re-set any of them only after ≥30 labelled pairs.
- **Chunk-table hygiene (2026-09-02).** Fresh compiles prune chunk rows that are not part of the run (`TerrainStore.delete_chunks_not_in`) — content-derived ids left 11 orphan rows embedded with a different model on an Aug-12 run; the chunk stage also logs how many documents produced no chunks (87 of 661 on the same corpus, all < 200 bytes).

### Pending — extraction signals

- **Reference-affinity signals beyond wikilinks + mentions.** The Stage 4 clustering blend uses `chunk_refs = wikilinks ∪ mentions`. Wikilinks are almost exclusively an Obsidian convention; Notion/Confluence/Jira chunks rarely populate that set, weakening the blend's value for those sources. Per-source extensions worth adding:
  - **Internal URLs** — URLs pointing back into the workspace (e.g., `notion.so/<workspace>/...`, `<company>.atlassian.net/...`). Already captured in `TerrainChunk.urls`; need a workspace-domain filter and inclusion in the refs set.
  - **Notion page mentions** — `@`-mention blocks that render to URLs in the harvester markdown. The Notion harvester would need to emit a separate `page_mentions` field.
  - **Confluence `ac:link` macros** — already partially captured by `urls`; explicit detection during normalization would tag them as internal references.
  - **Jira issue links** — `epic-link`, `blocks`, `caused-by`. The Jira harvester knows these structurally; surface them on `TerrainChunk.mentions` with a typed prefix.
  - The blend formula stays the same; we just feed it more signal. Expected impact: Notion-heavy corpora start benefiting from the same sparse-note clustering boost Obsidian users get today.

### Pending — entity layer

- **Drop the `SequenceMatcher.ratio() ≥ 0.85` canonicalization threshold to ≥ 0.88** (per-type already applied, but the threshold itself is permissive). At 0.85, "Alice" / "Alex" / "Alec" all merge, which is a real bug for person entities. Suggest tightening, OR using a stricter rule for `person`-type labels specifically (a 4-character person name shouldn't merge with another 4-character name on a 3-character overlap).
- **Per-workspace entity-type taxonomy.** The current set `{person, product, project, customer, concept}` is fine for a SaaS-product company; users in other domains (a law firm, a hospital) would benefit from custom types (`case`, `patient`, `regulation`, `procedure`). Surface via `mnemify.yaml`. (Generalized further by Stage 5.5.)
- **Entity-vs-tag conceptual overlap.** A name like "Phoenix" can legitimately be both an entity (the thing) and a tag (the topic). Today we emit both nodes and connect them via `belongs_to_theme`. That's correct, but the chatbot bundle can include both citations side-by-side, which is confusing. Consider deduping in the rerank when an entity and tag share a normalized label.

### Pending — Stage 4 quality

- **Confidence scores need calibration.** The current `inferred` confidence for `co-occurs` / `region-rel` is `clamp(weight, 0.3–1.0)`. That assumes the weight axis (Jaccard-style noteCount overlap) is comparable to a confidence axis (LLM trust). It mostly isn't. Want to revisit by measuring whether 0.6+ edges actually carry higher truth in a labeled test set.

### Pending — Citation → hex map feedback loop

Stage 5 wired tag-citation chips to `setSelectedTagId` so a click in Ask highlights the tag on the 3D map (the chatbot and brain share one selection state via the URL `?tag=` param). The flow works end-to-end for **tag** citations. The pieces that are missing:

- **Entity citations are non-clickable.** A user reading "Alice owns Phoenix [c2]" can't click `[c2]` to do anything — the chip is disabled because `citation.node_type === "entity"`. We need an entity-selection surface on the brain map. Two options:
  - Option A — **navigate to the entity's home tag**. Resolve `entity → belongs_to_theme tag` (highest weight), then `setSelectedTagId(tagId)`. Cheap; reuses existing tag-selection plumbing; the user lands on the right region of the map.
  - Option B — **emit an entity-detail drawer** mirroring the existing `TagProvenanceDrawer`. New component, new URL param (`?entity=`), new store field. Heavier but lets us surface entity-specific provenance (which notes mention it, which tags it belongs to, co-mention neighbors).
  - Recommend Option A for now, Option B when entity counts get high enough on real corpora that users want a dedicated view.
- **Region citations are non-clickable.** Same shape as entities. Region citations should focus the camera on the region (existing `focusRegionIdx` store field already supports this — wire `setFocusRegion(regionIdx)` from the citation click).
- **Note citations — frontend wiring pending.** The backend now surfaces note citations (notes inherit a discounted score from connected tags/entities, so they reach the bundle with citation ids). Remaining work is frontend: fire `openDoc(noteId)` from the chip so the user reads the source via the existing `DocDrawer`.
- **No bidirectional sync.** When the user clicks a hex on the brain map, the Ask panel does *not* scroll to or highlight any prior citation that referenced that tag. Add: when `selectedTagId` changes, find the most recent assistant message whose citations include that node id and highlight the corresponding chip.
- **Visual cue when selection arrives from Ask.** Today the spire highlight on Ask-driven selection looks identical to a hex-click selection. Adding a one-shot pulse animation on Ask-driven highlights would tell the user "this was triggered by the chatbot, here's the thing it was talking about." Small UX change, big legibility win.
- **Provenance hover on chips.** The chip already encodes provenance via border style (solid / outline / dashed). Adding a hover tooltip that spells it out ("This connection was explicitly written by you" / "This connection was inferred by the LLM, 0.62 confidence") would teach users to read the visual encoding without a key.

### Pending — observability

- **Compile-time emission counters.** *(Partially applied 2026-09-02: the render stage now reports regions/tags rendered vs compiled and land hexes — see the Applied log. The graph-stage counters below are still pending.)* Stage 4 / 4.5 / 4.6 add hundreds of nodes and edges per compile but we don't currently report a per-stage count in the progress events. The Stage 5 UI is also blind to "this corpus has no entity nodes because no entity cleared the eligibility threshold." Add `{stage: "graph_view", regions: N, tags: N, entities: N, edges: {by_type...}}` events.
