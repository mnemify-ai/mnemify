# The Ask Pipeline — `/api/ask` chatbot, retrieval, and citations

> How a user question becomes a grounded, cited answer. Covers the full
> path: query understanding → hybrid graph retrieval → raw-chunk expansion
> → SSE streaming → cited-only citation chips in the UI. Reflects the v0.8
> chat-quality overhaul (cited-only chips + retrieval fixes). For the
> pipeline that *produces* the artifacts this reads, see
> `terrain_improvements.md` (Stages 4–5).

---

## 1. Big picture

```
 user question (frontend AskPanel)
   │  POST /api/ask  (BYOK key in Authorization: Bearer)
   ▼
 routes_ask.ask()
   ├─ load .mnemify/terrain.json  → BrainMap.graph (GraphView)
   ├─ understand_query()             one cheap LLM call → {nodeTypes, mentions, topicIntent}
   ├─ embed topicIntent (or query)   OpenAI if key present, else local hash
   ├─ dimension guard                query dim ≠ graph dim → 503 (no silent empty bundle)
   ├─ ask_chunks.search()            query → raw chunk vectors (terrain.db) → note seeds
   ├─ ask_retrieval.retrieve()       seed → walk → rerank → floor → bundle (≤15 items)
   ├─ ask_expansion.expand_bundle()  attach raw chunk text from .mnemify/terrain.db
   └─ stream SSE:
        retrieval_debug → citations → delta* → citations_used → done
```

Three modules under `backend/src/api/`:

| Module | Responsibility |
|---|---|
| `routes_ask.py` | HTTP/SSE plumbing, guards, event ordering, BrainMap mtime cache |
| `ask_retrieval.py` | Pure retrieval: seeding, graph walks, rerank, bundle, citation parsing |
| `ask_chunks.py` | Chunk-level semantic search: cached numpy index over raw chunk vectors |
| `ask_expansion.py` | Dereference bundle items to raw source chunks in `terrain.db` |
| `ask_providers.py` | Provider transport (`anthropic` httpx, `openai` SDK, `claude` local CLI) + query understanding |

Frontend counterpart: `frontend/web/src/ask/` (`AskPanel.tsx`,
`useAskStream.ts`, `types.ts`, `OracleOrb.tsx`).

**BYOK contract.** The chat-LLM key arrives per-request in the
`Authorization` header and is forwarded to the provider — never persisted or
logged. Query-side embeddings use the *server's* `OPENAI_API_KEY` (the same
key the compile used) so query vectors are comparable to stored graph
vectors. The `claude` provider needs no key (local subscription CLI).

**Data the ask path reads** (read-only; it introduces no persistence):

- `.mnemify/terrain.json` — the layered graph (`BrainMap.graph`), parsed
  once and cached in-process by file mtime (compiles rewrite it atomically).
- `.mnemify/terrain.db` — read twice per question: `ask_chunks` searches
  the raw chunk *vectors* (cached numpy index, also mtime-keyed) and
  `ask_expansion` pulls the raw chunk *text*. Both added in v0.8; before
  that the chatbot only ever saw compiled summaries, which is why detail
  questions failed (note excerpts are truncated to 160 chars at compile
  time, and tag notes are distilled from at most 12 chunk summaries).

---

## 2. Retrieval (`ask_retrieval.retrieve`)

Six steps over the `GraphView` (nodes: `note` L0, `entity` L1, `tag`/`signal`
L2, `region` L3):

1. **Query understanding** — best-effort LLM call (`understand_query`, 7s
   timeout, never raises) returns `{nodeTypes, mentions, topicIntent}`.
   The last 2 chat turns are included in the prompt so elliptical follow-ups
   ("what about error handling?") resolve to the prior topic before
   embedding. Falls back to regex mention extraction (`@handles`,
   `[[wikilinks]]`, capitalized phrases) on any failure.
2. **Parallel seeding** across five sources:
   - entities by mention/label substring match,
   - **notes by chunk-level search** (top `CHUNK_NOTE_SEED_K = 6`) — the
     query is cosine-matched against *raw chunk vectors* (`ask_chunks.py`:
     top `CHUNK_SEARCH_K = 8` chunks above `MIN_CHUNK_SCORE = 0.2`), and
     matched chunks seed their parent note nodes. This is the only seeding
     path that sees full source text rather than a compiled distillation,
     and the only one that can distinguish sibling notes under one tag,
   - tags by cosine (top `TAG_SEED_K = 5`),
   - regions by cosine (top `REGION_SEED_K = 2`) — added in v0.8; regions
     were previously unreachable,
   - signals by cosine + severity nudge (top `SIGNAL_SEED_K = 6`).
3. **Within-layer 1-hop walk** from each seed (up to `WITHIN_LAYER_K = 5`
   neighbors; edges must pass `MIN_EDGE_WEIGHT = 0.4` *and* a per-type
   confidence floor: `EDGE_CONFIDENCE_FLOORS` gives the inferred lateral
   types `linked-to` / `co-occurs` / `region-rel` a 0.45 floor — the
   compiler emits them at ≤0.5, so the old uniform `MIN_EDGE_CONFIDENCE =
   0.6` gate made them all unwalkable — while everything else keeps 0.6).
4. **Cross-layer walk** for the first 6 seeds, allow-listed edge types:
   `mentions`, `belongs_to_theme`, `belongs-to`, `has-signal`, and (v0.8)
   `contains` (region ↔ tag).
5. **Rerank** of at most `CANDIDATE_CAP = 40` candidates. On overflow, all
   seeds are kept and remaining slots fill by semantic score (v0.8 —
   previously insertion order, which could crowd out strong late candidates).
   Score = `w_sem·semantic + w_rec·recency + w_cent·centrality +
   w_pers·affinity` with defaults `0.55/0.15/0.10/0.20`. Until Stage 6
   supplies `user_affinity`, the three live weights renormalize to sum to 1
   (v0.8 — the personal weight used to be dead weight). Nodes matching the
   understanding's `nodeTypes` hint get `NODE_TYPE_BOOST = 0.05` (a boost,
   never a filter). Notes have no embedding; they inherit their
   best-connected neighbor's score × edge weight × `NOTE_SEM_DISCOUNT = 0.85`
   — **unless a chunk hit supplies direct evidence**, in which case the
   note's semantic score is `max(inherited, best chunk cosine)`. Semantic
   similarity for embedded nodes compares the query against
   `0.7·context_embedding + 0.3·embedding` (`CONTEXT_BLEND`).
6. **Bundle** — top `TOP_K_RERANKED = 15` items become `c1..cN` with label,
   summary (≤1200 chars), edge provenance back to the nearest seed, source
   ids, and (v0.8) the rerank `score`. A relevance floor
   (`MIN_ITEM_SCORE = 0.08`) drops the weak tail, always keeping at least
   `MIN_BUNDLE_ITEMS = 3` so retrieval degrades gracefully instead of
   answering from nothing.

All thresholds are named module constants in `ask_retrieval.py` /
`ask_expansion.py` — no config files, per project convention.

---

## 3. Raw-chunk expansion (`ask_expansion.expand_bundle`)

The single highest-impact fix in v0.8. Compiled summaries orient the model;
raw chunks let it actually answer.

- Expands **note** and **signal** items only (tags/regions already carry
  compiled notes up to 1200 chars).
- Budgets: `EXPANSION_BUDGET_CHARS = 24_000` (~6k tokens) per question,
  `PER_ITEM_CHUNK_CAP = 3` chunks and `PER_ITEM_CHAR_CAP = 4_000` chars per
  item, walked in bundle (score) order.
- Chunk resolution: signals carry `sourceChunkIds` directly; note nodes are
  stamped with `sourceChunkIds` at graph emission (v0.8, `compiler.py`),
  and **older artifacts** resolve through the note-id derivation
  `n-{short_hash(doc_id, 8)}` against `terrain.db`'s chunks table — no
  recompile required.
- Chunks that matched the query directly (`ask_chunks` hits) are moved to
  the **front** of their note's expansion list, so the budget is spent on
  the text that actually matched rather than the doc's first chunks.
- Each excerpt is prefixed `[Doc Title > Heading > Path]` so the model can
  attribute what it quotes.
- Degrades gracefully: missing/unreadable `terrain.db` → bundle unchanged,
  `retrieval_debug.raw_chunks_expanded` stays `false`.

---

## 4. SSE wire protocol

`POST /api/ask` responds with an SSE stream, in this exact order:

| # | Event | Payload | Notes |
|---|---|---|---|
| 1 | `retrieval_debug` | seeds, selected node ids, `context_item_count`, `estimated_context_tokens`, `raw_chunks_expanded`, `expanded_chunk_count`, `expansion_chars`, `chunk_search_hits`, `chunk_seeded_note_ids` | debugging surface; the frontend currently discards it |
| 2 | `citations` | full metadata for every bundle item (`citation_id`, `node_id`, `node_type`, `layer`, `label`, `edge_provenance`, `source_note_ids`, `source_chunk_ids`, `score`) | sent up-front so the UI can resolve `[cN]` markers as they stream |
| 3 | `delta`* | `{text}` chunks | the answer, containing inline `[cN]` markers |
| 4 | `citations_used` | `{used: ["c1","c3"], fallback: bool}` | **v0.8.** Ids the answer actually referenced, parsed server-side (`extract_used_citations`: deduped, first-appearance order, hallucinated ids dropped). If the model cited nothing, `fallback: true` with the top-5 scored items |
| 5 | `done` | `{}` | |
| — | `error` | `{message}` | replaces 4–5 on stream failure |

Pre-stream failures are plain HTTP errors (no SSE): `401` missing key,
`409` no compiled terrain / no graph, `503` embedding-dimension mismatch or
embed failure with no seeds (see §6), `500` terrain load failure.

---

## 5. Frontend — cited-only chips

The chips under an answer show **only the items the answer cited**, not the
whole retrieval bundle (the pre-v0.8 behavior that buried users in 15 chips).

- `useAskStream.ts` parses `[cN]` markers out of the accumulated text on
  every delta, so chips appear live as the model cites; the server's
  `citations_used` event reconciles authoritatively at the end (covering the
  fallback case).
- `AskPanel.tsx` maps `usedCitationIds` → chip components in citation order.
  Nothing renders before the first marker arrives. Fallback sets get a muted
  "related context" label.
- `[cN]` markers stay visible in the answer text (deliberate: they map
  sentences to chips; upgrading them to inline clickable superscripts is a
  polish item).
- Chip click-through: `tag` citations highlight the 3D map via
  `onTagSelect`. Entity/region/note chips are not yet clickable — see
  "Pending — Citation → hex map feedback loop" in `terrain_improvements.md`.

---

## 6. Failure modes & guards

| Symptom | Cause | Behavior |
|---|---|---|
| 503 "embedding dimension … does not match" | Graph compiled with OpenAI vectors (1536/3072-dim) but query embedded with the 64-dim local hash fallback (`OPENAI_API_KEY` missing at ask time), or `embedding_model` changed in compile settings without recompiling | Hard error before the stream starts (v0.8 — previously the mismatch made every cosine 0, silently emptying retrieval, and the model answered confidently with no context: the classic "chat seems dumb" report) |
| 503 "query embedding failed and no entity mentions matched" | Embedder threw *and* nothing seeded | Hard error; an entity-seeded answer without semantic scores is still allowed |
| Fully offline mode still works | Graph *also* compiled with local hash embeddings → dims match | No error; lower-quality retrieval by design |
| `citations_used.fallback: true` | Model ignored the citation instruction | Top-5 scored items shown as "related context" |
| `raw_chunks_expanded: false` in `retrieval_debug` | `terrain.db` missing/unreadable | Answer from compiled summaries only — expect shallower answers |
| `chunk_search_hits: 0` on every question | `terrain.db` predates `embedding_hash` stamping (compiled before v0.8) | Chunk-level seeding silently off; **run one compile** (cheap — all caches hit) to stamp the column |

---

## 7. Tests & manual verification

Automated (`backend/tests/`): `test_ask_retrieval.py` (seeding, walks,
rerank math, floor, cap, citation parsing, chunk-hit tie-breaking, edge
floors), `test_ask_chunks.py` (index build, cosine ranking, score floor,
dim handling, stamping round-trip), `test_ask_expansion.py` (chunk
resolution incl. the doc-id hash fallback, budgets), `test_ask_route.py`
(SSE ordering, `citations_used`, fallback, 503 guards).
Frontend: `useAskStream.test.ts`.

**Golden-set eval** (`scripts/ask_eval.py`) — run the real retrieval stack
(no chat LLM) over corpus-specific questions and check the expected
material reached the bundle. Copy `scripts/ask_eval.example.yaml` to
`.mnemify/ask_eval.yaml`, fill in questions from your corpus, then
`python -m scripts.ask_eval`. **Run it before and after changing any
retrieval constant** — this is the difference between tuning and guessing.

Manual smoke (against a real compiled corpus, see `TESTING.md`):

1. Ask a detail question you know is documented → answer should quote it;
   `retrieval_debug` shows `raw_chunks_expanded: true`.
2. Watch the chips: none before the answer streams, only cited ones after,
   count well under 15.
3. Ask a "what is the X area about?" question → a `region` citation appears.
4. Ask a follow-up ("what about …?") → retrieval stays on-topic.
5. Unset `OPENAI_API_KEY` (OpenAI-compiled terrain) → clear 503 in the chat
   UI, not a hollow answer.

---

## 8. Known gaps (deliberate, v0.8)

- **Chunk-level search needs one post-v0.8 compile** — `embedding_hash`
  stamping happens during enrich; older `terrain.db` rows are NULL and the
  index is empty (the ask endpoint still works, just without chunk seeds).
- **Tags/regions are never chunk-expanded** — they rely on compiled notes.
  If tag-level detail questions underperform, expand tags via their
  `source_note_ids` as v2.
- **`retrieval_debug` is discarded by the frontend** — a debug panel showing
  seeds/scores would make retrieval issues user-diagnosable.
- **`[cN]` markers are plain text** — inline superscript rendering with
  chip-hover is the natural next polish step.
- **History is client-echoed and unvalidated** — the server trusts the
  `history` array from the client verbatim (local-first, single-user, so
  low risk today).

*Last updated: 2026-08-11 (v0.8 chat-quality overhaul + chunk-level
semantic search, lateral edge floors, BrainMap caching, golden-set eval).*
