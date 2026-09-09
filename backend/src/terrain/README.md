# Semantic Terrain

Builds a semantic density map from harvested normalized documents.

## Package layout

- `agents/`: LLM-backed execution nodes. Feature extraction and cluster naming use Pydantic AI agents; embeddings use the OpenAI SDK.
- `preprocessing/`: manifest reading, markdown chunking, and deterministic local feature extraction.
- `pipelines/`: end-to-end orchestration for terrain builds.
- `utils/`: Pydantic models, persistence, clustering, layout, naming fallback, embeddings fallback, and JSON emission.

## Steps

1. Read active documents from `.mnemify/harvest-manifest.db`.
2. Split markdown into heading-aware chunks with LangChain text splitters.
3. Preserve source hierarchy on every chunk: source, document, parent, ancestors, breadcrumbs, heading path.
4. Extract chunk features with a Pydantic AI structured-output agent: summary, products, customers, entities, tags, kind, attention signal drafts.
5. Build embedding text from extracted features and embed with `text-embedding-3-large`.
6. Group chunks into semantic regions and peaks with stable fingerprint-based IDs.
7. Name regions and peaks with a Pydantic AI structured-output agent.
8. Assign stable terrain positions from cached layout seeds.
9. Extract and aggregate source-grounded attention signals: todos, risks, decisions, open questions, owners, and recent changes.
10. Derive counts, top notes, subtopics, source refs, attention scores, and edges.
11. Compile region/tag summaries and a chatbot-oriented graph view.
12. Validate and write `.mnemify/terrain.json`, `.mnemify/mocknotes.json`, and `.mnemify/render-data.json` atomically.

## Algorithms

- Chunking: LangChain `MarkdownHeaderTextSplitter` + deterministic word-window splitting, with local fallback.
- Extraction: typed Pydantic schema via Pydantic AI.
- Embeddings: OpenAI `text-embedding-3-large`.
- Clustering: HDBSCAN over semantic embeddings. The LLM names stable clusters after the fact; it does not decide the structure.
- Naming: cached Pydantic AI agent output by cluster fingerprint.
- Layout: deterministic radial placement with persisted seeds.
- Attention: extraction of `todo`, `risk`, `decision`, `open_question`, `owner`, and `recent_change` signals, source-grounded either way. In `openai`/`claude` mode, `todo`/`risk`/`decision`/`open_question`/`owner` are drafted by the same per-chunk LLM call as feature extraction (negation-aware — "not a problem" doesn't read as a risk). `local` mode, and any chunk where LLM extraction fails, falls back to deterministic regex extraction. `recent_change` is always computed structurally from `source_modified`. Signals roll up to `attentionScore` / `attentionLevel` on every region and tag.
- Retrieval: `/api/ask` reads the compiled `GraphView` from `terrain.json`, seeds retrieval from regions, tags, entities, and attention signals, and cites source notes/chunks. Raw chunks are not the first retrieval layer.
- Output: Pydantic validation before atomic JSON write.

## V1 boundaries

The terrain is read-only in V1. It is an active retrieval and navigation layer over source systems, not an editor and not a writeback engine. Operational facts are facets over the semantic terrain:

- The semantic tree controls geography.
- Attention signals control burn/importance overlays and region-panel sections.
- Chat uses compiled terrain summaries and graph links before expanding to source notes.
- Source pages remain the system of record.

## Commands

Run with Pydantic AI extraction/naming and OpenAI embeddings:

```bash
python -m src terrain build
```

Requires `OPENAI_API_KEY` and `pydantic-ai-slim[openai]`. For deterministic local development/tests:

```bash
python -m src terrain build --ai-mode local
```

The compiler stores cache/state in `.mnemify/terrain.db`, including chunks, features, embeddings, cluster assignments, names, layout seeds, and build runs.
