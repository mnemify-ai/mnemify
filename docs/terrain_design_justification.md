# Terrain v0.5 — Design Justification Memo

*Purpose: for each point your friend raised, the justification for the design choice as it stands — why this way and not another — and how it ladders up to the story we're telling in the AI space.*

**Our story, stated once so every choice can be measured against it:** Terrain is a *personal knowledge graph that is both a visual brain map and a grounded chatbot*. Three things make it defensible against generic RAG and against the big graph frameworks (GraphRAG, LightRAG, Graphiti): (1) **legibility** — every connection can explain *why* it exists; (2) **multi-path triangulation** — the same answer reachable through entities, themes, and notes, so the system can corroborate itself; (3) **local-first** — the user's brain stays on their machine. We don't adopt any framework wholesale; we graft the one pattern each gets right onto the thing only we have — the hex terrain. Every design choice below is in service of those three.

---

## Point 1 — Source-aware chunking (agreed)

**The choice:** replace one markdown chunker with a per-source dispatcher.

**Why this way:** chunking is the silent ceiling on everything downstream. A weak chunk produces a weak embedding, a weak extraction, a weak summary, a weak retrieval. Today every source is chunked as if it were a long clean document; real corpora are Notion sub-pages, Obsidian wikilink webs, Confluence tables. Fixing this isn't "smarter prompting" — the signal is destroyed *before* the model ever sees it. You cannot prompt your way back to information you've already shredded.

**Alignment:** garbage-in defeats the whole graph. If chunks are wrong, the entity layer is wrong, the summaries are wrong, the chatbot cites wrong. This is the foundation the triangulation story stands on.

## Point 2 — Preserve structural context (agreed)

**The choice:** stop discarding heading paths, wikilinks, mentions, frontmatter between chunking and the model; feed them to both the LLM prompt and the embedding text; blend reference-affinity into clustering.

**Why this way:** a chunk in isolation forces the model to *guess* what it's about. The structure that disambiguates it already exists in the source — we were throwing it away. Two notes both linking `[[Project Phoenix]]` should pull together even when their prose is sparse; pure cosine can't see that, a reference-affinity blend can.

**Alignment:** this is the first appearance of the "explicit signal beats inferred signal" principle that becomes the spine of the whole plan. A wikilink the user *wrote* is ground truth; an embedding similarity is a guess. We start preserving that distinction here, and it pays off as provenance in Stage 4.

## Point 3 — Compiled notes per tag and region (agreed)

**The choice:** synthesize a real LLM summary for every region and every important tag; embed them; cache by content hash.

**Why this way:** the chatbot needs *coherent retrievable units*. Chunks are too fragmented to retrieve over — you'd hand the model a mosaic and ask it to reassemble meaning under latency. A pre-synthesized, pre-embedded summary is the unit retrieval actually wants. The eligibility gate (top-15 by elevation) plus the extractive fallback for the long tail keeps cost bounded without leaving any tag un-retrievable. Content-hash caching makes re-compiles near-free, which is what lets us rebuild the whole brain every time instead of building incremental-update machinery we don't need yet.

**Alignment:** this is what turns a *map* into something a chatbot can *read*. It's the bridge between the visual product we have and the conversational product we're building.

---

## Point 4 — Leiden communities + confidence-labeled edges

> *Your friend: understands Leiden, fine with it, likes the algorithm.*

**The choice:** run Leiden alongside HDBSCAN as a *soft* signal (HDBSCAN stays authoritative for the hex layout), and tag every edge with **provenance** (`extracted` / `inferred` / `ambiguous`) and a **confidence** score.

**Why Leiden as a soft signal and not a replacement:** the two algorithms fail in opposite directions, so they cover each other. HDBSCAN is density-based — it dumps sparse items into a "noise" bucket, which is the right behavior for laying out a clean hex map but throws away real-but-thin communities. Leiden operates on the graph topology itself and finds those tight communities HDBSCAN discards. But we *cannot* let Leiden move the hexes — the spatial layout is the product's identity, and users build muscle memory on it. So Leiden gets a vote (a +0.1 edge-weight nudge when endpoints share a community), not a veto. This is the "cherry-pick, don't adopt" principle in miniature: we take GraphRAG's community detection without surrendering what makes terrain *terrain*.

**Why confidence labels are non-negotiable — this is the heart of the story:** today our edges are pure numbers, and a number can't tell the chatbot the difference between *"Alice and Phoenix are connected because the user literally wrote `[[Project Phoenix]]` in Alice's note"* and *"…because the LLM guessed it."* Those two facts deserve completely different treatment in an answer, and a system that can't tell them apart will state guesses with the same confidence as facts — which is exactly how RAG chatbots lose user trust. Provenance is what lets the chatbot say *"the notes explicitly say X; I'm inferring Y."* That single capability is our wedge against generic RAG: **we don't just retrieve, we show our work.** It's why the front end has solid/outline/dashed citation badges — the legibility goes all the way to the pixel.

**Honest caveats (watch items, not blockers):**
- *Surprising-connections is naive on small graphs.* `weight / (deg(u)×deg(v))` rewards rare-node pairs regardless of meaning; on a 50-node graph the top-20 is mostly noise. Gate by `min(deg) ≥ 3` and a minimum weight before this feeds the Daily Briefing — it's a first-impression feature, and "non-obvious link" had better not mean "random pair."
- *Confidence isn't calibrated yet.* The `inferred` score borrows the Jaccard weight axis as if it were a trust axis; those aren't the same thing. Ship it, but validate against a small labeled set before the chatbot is allowed to make hard claims off a `0.6`.

## Point 4.5 — Entity promotion to first-class nodes

> *Your friend: agrees; wants this as `entity_metadata` in the graph, traversable.*

**The choice — and the one distinction that matters here:** promote entities (Alice, Project Phoenix, the Stripe API) to **first-class nodes with their own embedding and their own edges**, rather than hanging them off existing nodes as a metadata bag.

You said "entity_metadata… in the graph that we have for traversal." We agree on the goal and want to be precise about the mechanism, because the mechanism is the whole value: **metadata you can filter; a node you can traverse.** If Alice is an attribute stored on five chunks, answering *"what do we know about Alice?"* means scanning for clusters that happen to contain her and hoping. If Alice is a node, the same question is *one hop* — and her edges to the notes that mention her, the tags she belongs to, and the other entities she co-occurs with are all directly walkable. Traversal is the verb; only a node supports it. So "metadata for traversal" specifically requires node-promotion — they're the same wish, and node-promotion is how it comes true.

**Why this is the biggest leap in the plan:** today our tags are *topics* — named clusters of chunks. The actual *things* people care about — people, products, projects — are buried inside chunk text and never surface as their own object. Promoting them is what enables **triangulation**, the second pillar of our story: the chatbot can reach an answer through the entity layer *and* through the theme layer, and prefer the points where both agree. That's a corroboration mechanism generic vector RAG simply does not have — it has one path (nearest chunks) and no way to cross-check it.

**Why the layered structure (regions → tags → entities → notes):** the layers give every cross-layer edge a *meaning* (`mentioned_in`, `belongs_to_theme`, `mentions`) instead of an anonymous similarity. Meaningful edges are what make the graph legible *and* what make Stage 5's directional cross-layer walk possible. This is GraphRAG's "entities as first-class citizens" pattern grafted onto our weighted-membership terrain — adopted because it directly serves triangulation, not because the framework has it.

**Two corrections to fold in now, not later:**
- *Tighten canonicalization 0.85 → 0.88 (or a stricter person-rule).* At 0.85, "Alice / Alex / Alec" merge. That's a correctness bug, not a tuning knob — and it bites hardest on exactly the person-entities the chatbot will be asked about most.
- *Dedup entity-vs-tag in the answer bundle.* "Phoenix" can legitimately be both an entity and a tag; emitting both nodes is correct in the graph, but two near-identical citations side-by-side in one answer reads as confusion. Dedup at rerank on the normalized label.

## Point 4.6 — context embeddings: tree vs. graph

> *Your friend: agrees context embedding is needed, but is confused — this feels like it should be a tree, not a graph; worries every context gets tracked to every context; imagines context as flowing from a start to an end, "a folder way of information flow"; wants Claude's take.*

This is the deepest and best objection in the whole review, and it dissolves once we separate two things that are both wearing the word "context."

**1. Stage 4.6 is context *smoothing*, not context *traversal*.** GraphSAGE here is not a walk through the graph — it's a one-shot operation where each node blends a little of its *immediate* neighborhood into its own vector. It has no start and no end because **nothing is moving**; each node simply becomes "itself, tinted by its surroundings." The concrete payoff: two tags both labeled "Launch" — one marketing, one engineering — have nearly identical text embeddings and would be indistinguishable to search. After smoothing, each is tinted by a completely different neighborhood, so search can finally tell them apart. That's the entire job of 4.6, and it requires no notion of direction or flow.

**2. Your "start point / end point / context across depths" instinct is exactly right — it just lives in Stage 5, not 4.6.** What you're describing — information that begins somewhere, travels across several hops, and arrives somewhere — *is* the retrieval algorithm. Stage 5 starts at the query's seed nodes, walks a bounded number of hops across the layers, and ends at a capped answer bundle. It is directional, it has a beginning and an end, and it gathers context across depth. So the plan already honors your mental model — you were looking for it one stage too early. 4.6 builds better *vectors*; Stage 5 does the *journey*.

**3. "Does every context get tracked to every context?" — no, and the reason is the design's main safety knob.** The plan specifies **2 GraphSAGE layers**, which means each node only ever sees its **2-hop neighborhood** — never the whole graph. The runaway contamination you're picturing (everything bleeding into everything) only happens if you stack *many* layers; that failure has a name — **oversmoothing** — and the symptom is precisely what you intuited as bad: every node's vector converges to the same blur and retrieval can no longer discriminate. Your instinct is correct; the standard remedy is "keep it shallow," and the doc already does. So: **bounded mixing is good** (it's what disambiguates Launch-vs-Launch); **unbounded mixing is bad** — and 2 hops sits on the right side of that line by design.

**4. The "folder way of information flow" you're reaching for already exists — it's the other half of the system.** A folder/tree model is hierarchical roll-up: a region means the sum of its tags, a tag means the sum of its notes and entities. That is *exactly* the region → tag → note hierarchy plus the community summaries from Stages 3–4. **You already have the tree.** GraphSAGE is the *lateral* signal layered on top of it — the sibling-to-sibling and branch-to-branch links a tree can't express.

So the real question isn't "tree or graph." It's "do the lateral cross-links earn their cost?" — and the answer is yes, *because of our own marquee feature.* A pure tree forces every node to choose exactly one parent and discard every other relationship. That means *"this note quietly bridges two unrelated regions"* — the single most interesting thing a knowledge tool can tell you, and the thing Stages 4 and 7 are built to surface — becomes **unrepresentable**. A tree literally cannot hold a surprising connection. Real knowledge is a graph: an entity belongs to two projects, a note is tagged in two regions. Collapsing to a tree throws exactly that away.

**The recommendation, and why it fits the story:**
- **Keep the graph as the source of truth; expose tree *views* on top for navigation.** You get the folder-like drill-down you want for the UX *and* the cross-links that power triangulation and surprising-connections. The hierarchy is for *scoping*; the graph is for *discovery*. Both, not either.
- **For v0.5, ship the mean-of-neighbors baseline specifically — not random-weight GraphSAGE.** The doc's verify test ("context_embedding diverges by ≥0.05") only proves the vectors *moved*, not that they moved *usefully* — random initialization can move them in noise. Mean-of-neighbors delivers the disambiguation benefit deterministically, in ~30 lines, with no `torch` dependency. It's the honest v0.5 choice.
- **Defer the version that respects your directional intuition to v0.6.** A typed/directed message-passing model (R-GCN) would let context flow *up* the hierarchy — notes → entities → tags → regions — instead of mixing undirected. That's the closest thing to the "flow from a start toward an end" you were describing, and it's the right v0.6 upgrade once Stage 5 quality numbers justify the dependency. Because the plan emits `context_embedding` either way, this upgrade is non-breaking.

**Net:** don't fight the graph. The tree you want is already present as the hierarchy; the graph is what makes the product more than a folder browser — and a folder browser is not a story worth telling in the AI space.

## Point 5 (Stage 5) — the chatbot is "easy: just retrieval and display"

> *Your friend: this falls out easily, it's retrieval of what we have plus display.*

Architecturally, agreed — Stage 5 retrieves over objects we've already built. As head of AI I'll register one precise pushback: it's **easy to build and hard to make good, and with a chatbot the retrieval quality *is* the product.** Everything in Stages 1–4.6 exists to make this stage good; if we treat it as plumbing, we waste the foundation. The way "easy" turns into "shipped and mediocre" is four specific gaps, all already on the TODO list:

- **Query understanding is regex** (`[A-Z][\w-]+`). It seeds on proper nouns and misses paraphrases — "the OCR work" never reaches the "OCR Pipeline" tag. One cheap `gpt-4o-mini` call returning `{nodeTypes, mentions, topicIntent}` closes it.
- **The recency term in the four-signal rerank is wired to 0** — `GraphNode` carries no recency field. Stamp recency onto the node during graph emission so the term actually fires.
- **The rerank weights (0.55 / 0.15 / 0.10 / 0.20) are hand-picked.** Tune against a small eval set before we call retrieval "done."
- **The citation → hex-map loop only works for tag citations.** Entity, region, and note citations are non-clickable. That click *is* the demo — the moment the chatbot and the brain map prove they're one product — so it's worth finishing.

**Alignment:** this is where all three pillars become visible to the user at once — legibility (provenance badges), triangulation (entity + theme evidence agreeing), local-first (their key, never logged). The architecture is easy because we front-loaded the hard work; the quality is the part that earns the user.

## Point 6 (Stage 6) — personal-graph layer: agreed, next version

**The choice and the deferral:** log local interactions, derive a per-tag `userAffinity` with exponential decay, feed it into the Stage 5 rerank — and ship it *after* v0.5.

**Why defer is correct:** the rerank formula already reserves the `userAffinity` term and defaults it to 0, so the whole feature slots in **non-breaking** the day we have data — there's no architectural debt in waiting. And waiting is the right call because the feature is only meaningful *with* accumulated usage; shipping it on day one means scoring against an empty log. Let Stage 5 generate the interactions first, then derive affinity from real behavior.

**Alignment:** this is the local-first answer to Glean's Personal Graph. Glean derives behavior signals server-side across an enterprise; we do a simpler exp-decay slice entirely inside `.mnemify/`, nothing leaving the machine. It makes the chatbot feel like it knows what you're *currently working on* — the personalization payoff — without compromising the privacy pillar. That combination (personalized *and* local) is itself a differentiator worth stating out loud in the README.

---

## One-line summary per point

| Point | Verdict | The justification in a sentence |
|---|---|---|
| 1 Chunking | Ship | You can't prompt back signal you shredded before the model saw it. |
| 2 Structural context | Ship | Explicit signal the user wrote beats inferred similarity — and we start preserving that distinction here. |
| 3 Compiled notes | Ship | The chatbot needs coherent units to retrieve over; chunks are too fragmented. |
| 4 Leiden + confidence | Ship (2 watch items) | Soft Leiden covers HDBSCAN's blind spot; provenance is our wedge — we show our work. |
| 4.5 Entities | Ship (tighten canon + dedup) | "Metadata for traversal" *requires* node-promotion; nodes are what enable triangulation. |
| 4.6 Context embeddings | Ship mean-of-neighbors; R-GCN in v0.6 | It's smoothing not traversal; the tree already exists as the hierarchy; a pure tree can't hold a surprising connection. |
| 5 Chatbot | Ship (close 4 quality gaps) | Easy to build, hard to make good — and the quality *is* the product. |
| 6 Personal graph | Defer to next version | Slots in non-breaking; only meaningful once Stage 5 has generated usage. |

The through-line: every stage exists to make the chatbot **legible, self-corroborating, and private**. That's the story, and each choice above is defensible precisely because it serves one of those three.
