# Positioning & Competitive Landscape

> Competitive research completed August 2026. This is the strategy layer above
> [`ROADMAP.md`](ROADMAP.md): who we're up against, where the moat actually is,
> how we say what we are, and what could kill us. Product/UX priorities stay in
> the roadmap; this doc governs how we talk about and sequence them.

**What Mnemify is (for reference):** local-first AI context infrastructure.
Harvest from Notion/Confluence/Jira/Obsidian → compile into an emergent
semantic terrain (HDBSCAN clustering, not folder taxonomy) → surface as a 3D
hex map with source-grounded attention signals, citation-verified chat, and
context artifacts for downstream AI clients. Everything lives in a local
`.mnemify/` directory; BYOK for the model.

---

## 1. Competitive map

Honest scorecard. "They win" is what a fair reviewer would say against us today.

### NotebookLM / Gemini Notebook
- **They win:** the reference citation UX — inline, clickable, trusted by a
  mainstream audience. Free-ish, Google distribution, zero install.
- **We win:** it's *upload-a-corpus*, not *connect-your-stack* — no live
  Notion/Confluence/Jira harvest. Per-notebook silos mean no cross-corpus
  memory. Hallucination complaints are rising as usage scales.
- **Read:** the closest thing to a mainstream validator of "answers with
  citations." Also our biggest strategic threat (see §6).

### Glean
- **They win:** connector breadth nobody matches; the enterprise search
  category leader.
- **We win:** enterprise-only, roughly $50–75/user/mo with ~100-seat minimums —
  structurally unable to serve an individual. Reviews show real privacy
  discomfort with a vendor indexing everything centrally. We're local, solo,
  BYOK.

### Mem.ai
- **They win:** capture UX — frictionless note-in, pleasant recall.
- **We win:** it only knows what you typed into it. Mnemify knows what you
  actually worked on, because it harvests the systems where work already lives.

### Tana
- **They win:** structured supertags are genuinely powerful for people who
  commit to them.
- **We win:** brutal learning curve — Tana demands you restructure your entire
  workflow around its schema. Our counter-positioning, verbatim: **"change
  nothing, the map emerges."** Harvest is read-only; structure is computed,
  not imposed.

### Heptabase
- **They win:** beautiful hand-built spatial whiteboards; strong thinking-tool
  loyalty.
- **We win:** their space is manual, ours is compiled. The frame:
  **gardening vs. satellite imagery.** Heptabase rewards hours of arranging;
  Mnemify's terrain is emergent from embeddings and updates on recompile.

### Obsidian + AI plugins
- **They win:** local-first loyalist community, plugin ecosystem, file
  ownership.
- **We win:** the graph view is an illegible hairball at scale — links, not
  semantics.
- **Key note:** Obsidian is an **acquisition channel, not a competitor** — we
  harvest Obsidian vaults natively. "Your vault as terrain" is a growth loop
  (§5), not a battle.

### Khoj
- **They win:** ~35K-star open-source second brain; proves the OSS
  distribution model works in exactly our audience.
- **We win:** it's a chat box over your files without a compiled graph — no
  terrain, no attention layer, no structural memory.

### AnythingLLM
- **They win:** ~63K stars; the default local RAG infrastructure choice.
- **We win:** it's infrastructure wearing a generic chat skin. No product
  opinion about *your* work, no map, no signals.

### Rewind / Limitless
- **They win:** the ambient-capture dream; strong brand with early adopters.
- **We win:** acquired by Meta in Dec 2025, orphaning a cohort of
  privacy-sensitive users who chose it *because* it was private. Our line:
  **"your memory shouldn't be an acquisition target."** Local-first + open
  formats means there's nothing to be acquired out from under you.

### Recall
- **They win:** clean "remember what you consumed" pitch.
- **We win:** it indexes what you *read*, not what you *work on*. Different
  corpus, different job.

### Saner.AI
- **They win / lesson:** proof that a narrow persona positioning ("for people
  with ADHD") beats "for knowledge workers." We should copy the discipline,
  not the persona (§3).

### Summary table

| Competitor | Their edge | Our edge | One-line counter |
|---|---|---|---|
| NotebookLM | Citation UX, distribution | Connect-your-stack, cross-silo | Notebooks are silos; work isn't |
| Glean | Connector breadth | Local, solo, affordable | Glean for one person, on your laptop |
| Mem.ai | Capture UX | Harvests where work lives | It only knows what you told it |
| Tana | Structured power | Zero restructuring | Change nothing, the map emerges |
| Heptabase | Manual spatial canvas | Computed terrain | Gardening vs. satellite imagery |
| Obsidian+AI | Local-first loyalty | Semantic map at scale | (Channel, not competitor) |
| Khoj | OSS distribution proof | Compiled graph under the chat | Chat box ≠ terrain |
| AnythingLLM | OSS RAG infra | Product, not plumbing | Infra with a chat skin |
| Rewind/Limitless | Ambient capture | Not acquirable out from under you | Memory ≠ acquisition target |
| Recall | Read-capture | Work-capture | What you read ≠ what you work on |
| Saner.AI | Persona discipline | (Lesson, not rival) | Narrow beats "knowledge worker" |

---

## 2. Moat ranking

Ordered by defensibility × resonance with the 2026 buyer.

1. **Server-verified citations.** The server drops hallucinated `[cN]` ids
   before the answer reaches the user — a citation you see is a citation that
   resolved against `mocknotes.json`. Almost nobody in the space can claim
   this; everyone else's citations are model-emitted and hoped-for.
   Hallucination is the era's #1 AI anxiety (see NotebookLM's complaint
   curve). This is the lead claim.
2. **Local-first privacy.** A *qualifier* moat: it rarely wins the deal alone,
   but it removes the reason to say no — for the exact audience burned by
   Rewind and uneasy about Glean. Everything in `.mnemify/`, tokens in
   `.env`, BYOK, `--ai-mode local` needs no network at all.
3. **Visible agentic graph exploration.** Chat retrieval seeds from regions,
   tags, entities, and attention signals — and shows its steps. The 2026
   agent-UX consensus is settled: show the steps or trust collapses. Opaque
   RAG is now a liability.
4. **The attention/burning layer.** The sleeper — possibly the real product.
   Nobody else extracts todos, risks, decisions, and open questions *across
   tools* and renders them as heat on a stable map. This is the day-14
   retention feature: the reason to open Mnemify after the terrain-novelty
   wears off (see §6).
5. **3D semantic terrain.** The polarizing hook, not the value. It earns its
   keep only when it's interactive and task-linked (click a hex → panel →
   source). **Market it as the interface, never the product** — otherwise we
   invite the "pretty graph-view shelfware" dismissal.

---

## 3. Positioning

**One-liner:** *"See everything you know. Trust everything it says."*

**Three pillars:**

1. **A map, not a search box.** Orientation over lookup. The terrain shows
   the shape of your work; search boxes only answer questions you already
   knew to ask.
2. **Answers that prove themselves.** Every claim carries a server-verified
   citation back to a source note. Not "sounds right" — resolvable.
3. **What's burning right now.** The attention layer surfaces todos, risks,
   decisions, and open questions across all your tools as heat on the same
   map.

**Privacy is the frame around all three, not a fourth pillar.** It's the
paper the poster is printed on: local-first, BYOK, exportable, wipeable.
Stated everywhere, headlined nowhere.

**Beachhead persona:** the technical lead / senior IC drowning in
Notion + Confluence + Jira. They can run a local app, they supply an API key
or already pay for Claude Code, and they hang out where local-first is a
feature, not friction (HN, r/ObsidianMD, r/selfhosted). Saner.AI's lesson
applied: name this person in every headline until it hurts. **Expand later**
to PMs and consultants — only after the beachhead retains.

---

## 4. Naming critique

Honest assessment of "Mnemify":

- Sounds like a 2012 iPaaS / middleware product, not a knowledge tool.
- **Collides with Mnemify Hotspot** — an established Wi-Fi-sharing product
  with the SEO position and likely trademark friction.
- Says "connect" when the product's soul is terrain / memory / cartography.
  The connectors are plumbing; the name markets the plumbing.

**Decision rule:** if we don't rename, *always* pair the name with the
category tag — **"Mnemify — the knowledge terrain."** Never let the bare
name stand alone in a headline.

**Candidate direction words** if/when we rename: *map, terrain, atlas,
relief, ground truth.*

---

## 5. Growth-loop backlog

Future rounds — explicitly **not** this release. Ordered roughly by
leverage-per-effort:

| Loop | Mechanic | Precedent |
|---|---|---|
| Shareable terrain snapshots (with privacy mode) | Every share is a demo of the recipient's own potential terrain | Figma links |
| Public demo terrains of famous corpora | The Show HN linchpin — see the product without connecting anything | NotebookLM demos |
| Open-source the harvest/compile core | Stars → distribution → funnel to the surface app | Khoj (35K★), AnythingLLM (63K★) |
| MCP / context-artifact angle | "Give your coding agent your whole work memory" — the JSON artifacts are already built for this | MCP ecosystem |
| Obsidian bridge | "Your vault as terrain in 60 seconds" — harvester already exists | Plugin-directory distribution |
| Demo-first onboarding | Terrain before credentials; wire sources after the wow | Linear's demo workspace |

---

## 6. Strategic risks

1. **Gemini Notebook adds connectors.** The moment NotebookLM connects to
   Notion/Drive/Atlassian, our "connect-your-stack vs. upload-a-corpus" gap
   compresses to citations + local-first + terrain. **Speed matters** — the
   beachhead must be won before that ships.
2. **The day-14 test.** If the terrain is only novel, it becomes graph-view
   shelfware — Obsidian's hairball with better lighting. The burning layer is
   the mitigation: heat changes daily, so the map has a reason to be opened
   daily. Ship and measure it as the retention feature it is (the roadmap's
   Daily Briefing card is the same bet).
3. **The name.** SEO collision + category confusion compounds every marketing
   dollar. Decide (rename vs. category-tag discipline) before any public
   launch push; it only gets more expensive.
