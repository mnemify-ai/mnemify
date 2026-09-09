# Roadmap — what to build next

> Moved here from `frontend/ROADMAP.md` during the May 2026 cleanup. This is the
> product/UX menu; the engineering backlog (small follow-ups) is in
> [`BACKLOG.md`](BACKLOG.md).

**What's shipped today.** The 3D hex BrainMap reads the *compiled* terrain
(`/api/terrain/render-data`) — there's no baked demo dataset; a fresh install
shows the connect → harvest → compile onboarding screen. Around it: live
connection wizards (Notion / Obsidian / Confluence) under Settings, a `/harvest`
route with SSE progress / cancel / completion summary / history, a `/compile`
route with the same live-progress treatment plus a compile report (stats +
highlights), a virtualized DocumentsPage with URL-serialized filters,
manage-scope + an advanced filter editor per source, and `./run.sh` to bring up
the whole thing. (So the "Real-data swap" and "Onboarding checklist" items below
are **done**.)

**What this doc is.** The prioritized menu for what's next. Nothing here is
under construction. Pick from it.

---

## Jobs-to-be-done

Users come to Mnemify with four distinct jobs. Every feature below
maps to one.

1. **"Connect my tools to my brain."** The install moment — the wiring
   should just work. Today's wizards nail this.
2. **"Know what my brain already knows."** Daily orientation. *"What's
   new since I last looked? Which threads are heating up? Who/what
   should I pay attention to today?"* — partially answered by Home +
   Activity feed today, but shallow.
3. **"Use my brain to do work today."** Active use. *"Draft an email to
   Sarah about Project Atlas using my context. Pull every note that
   mentions OCR accuracy and summarize. Tell my AI what it needs to
   know before this call."* — barely addressed yet.
4. **"Trust my brain."** Continuous reassurance. *"Where is my data?
   What was harvested? Can I export it? Can I wipe it? Is the model
   sure about that claim or guessing?"* — partially addressed.

---

## Impact × effort matrix

| Feature | Job | User impact | Eng effort | Phase |
|---|---|---|---|---|
| ⌘K command palette | 2, 3 | High | Low (2–3d) | **v3 quick win** |
| Onboarding checklist | 1 | Med | Low (1d) | **v3 quick win** |
| Real-data swap (terrain-data.json → BrainMap) | 2 | Very high | Med (~1w) | **v3 cornerstone** |
| Daily Briefing card on Home | 2 | Very high | Med | v3 |
| Anthropomorphic micro-moments | 1, 2 | Med (delight) | Low | v3 (folded in everywhere) |
| Export `.mnemify` as zip | 4 | Med | Low | v3 |
| Reset everything | 4 | Med | Low | v3 |
| Audit log viewer | 4 | Med | Low | v3.5 |
| Scheduled harvests (cron) | 1 | Med | Low–Med | v3.5 |
| OAuth flows (Notion + Atlassian) | 1 | High (non-technical users) | Med–High | v4 |
| Ask / chat surface | 3 | Very high — core thesis | High (Reasoner) | v4 |
| Entity pages (people / projects) | 2, 3 | High | Med–High | v4 |
| Context-export bundles for AI | 3 | High | Med | v4 |
| Confidence + contradiction flags | 4 | Med (honesty) | High | v5 |
| Mobile companion | 2 | Low–Med | High | v5+ |
| Multi-workspace / team | 1 | Low for solo audience | Very high | v5+ |

---

## Feature paragraphs

### ⌘K command palette
The single highest-ROI quick win. Pressing ⌘K opens a search input with
three sections: notes (substring match across `mocknotes` titles +
excerpts), navigation (jump to any of the six routes + the connect
wizards), and actions ("Re-harvest Notion", "Open Compile Report").
Powered by `cmdk` (~3 KB), reads from the existing `BrainDataProvider` —
no new data plumbing. **Why it matters:** power users measure tools by
how fast they can navigate them. ⌘K turns a five-click flow into a
four-character flow.

### Onboarding checklist for first-time users
A small four-step overlay widget that appears on first visit and
persists to `localStorage.mnemify.onboarded`. Steps: ✓ Connect your
first source · ✓ Pick a scope · ✓ Run your first harvest · ✓ Click any
hex spire on the brain. Each step auto-checks when the user completes
it. Dismissible. **Why it matters:** guides the install moment without
modal friction. Today there's no feedback loop telling us if a new
user got past install.

### Real-data swap (terrain-data.json wiring)
The cornerstone v3 work. Today the BrainMap reads the committed
`render-data.json` (a baked snapshot of mock data). The backend
compiler produces a `.mnemify/terrain-data.json` from real harvested
documents — a semantic format, not yet in hex geometry.

Two paths:

- **(a)** Port `scripts/bake_render_data_v3.py` into the backend as a
  new emitter step in `backend/src/terrain/`, expose
  `GET /api/terrain/render-data` that returns the v3 hex format from
  the live `terrain-data.json`.
- **(b)** Extend the BrainMap to consume the semantic
  `terrain-data.json` directly and bake hex geometry client-side.

(a) is lower-risk and reuses the working Python; (b) is a multi-week
scene rewrite. **Why it matters:** today's dashboard is a polished demo
on top of real plumbing. After v3 it's the real thing.

### Daily Briefing card on Home
A card that appears at the top of Home each morning (or on first visit
of the day), dismissible. Renders compiled insights: *"3 new memories
formed since Tuesday · Sarah Chen mentioned in 4 new notes · OCR
accuracy is your most active topic this week."* For v3 against mock
data, the insights can be derived heuristics (latest activity, top tag
frequency, biggest weekly delta). For v4 against real data, the
Reasoner produces them. **Why it matters:** the daily touchpoint that
turns Mnemify into a habit, not a tool you forget about.

### Anthropomorphic micro-moments
Small touches everywhere: *"First synapse formed"* toast on first
connection (already shipping), *"Your brain learned N new memories"* on
harvest complete (already shipping), *"Memory wiped. Ready when you
are."* after reset, particle burst on a successful Notion connect,
optional chime on harvest complete (off by default, toggle in
Settings). **Why it matters:** shifts the product from "another
dashboard" to "the brain that lives on your laptop." None of these are
expensive — they're copy + small motion.

### Audit log viewer
A new route `/audit` (or a Settings sub-page) that renders the JSONL
audit log the backend already writes to `.mnemify/audit-log.jsonl`.
Searchable, filterable by action type (harvest, fetch, skip, error,
save-credentials). Needs a paginated backend endpoint
(`GET /api/audit-log?page=…`). **Why it matters:** trust. Users can see
*exactly* what Mnemify did and when. Particularly important for
users plugging Mnemify into privacy-sensitive workflows.

### Export `.mnemify` as zip + Reset everything
Two Settings actions:

- **Export** packages `.mnemify/` (manifest + raw + normalized) into
  a downloadable zip via `GET /api/export`.
- **Reset**, after a double-confirm AlertDialog, wipes credentials from
  `.env`, sets all `enabled: false` in `mnemify.yaml`, deletes
  `.mnemify/raw/` + `.mnemify/normalized/` +
  `.mnemify/harvest-manifest.db`. Backs up to `.mnemify-backup/`
  first.

**Why it matters:** portability + control. The user knows they can take
their brain with them or nuke it without leaving the app.

### Scheduled harvests
Cron-style configuration in Settings ("Every morning at 6am" etc.) that
runs a harvest via a backend daemon. Needs backend support for the
schedule itself. **Why it matters:** set-and-forget; the brain stays
fresh without the user remembering to click.

### OAuth flows
Replace paste-token wizards with proper OAuth for Notion + Atlassian.
Token-paste is fine for technical users but is the #1 drop-off for
non-technical ones. Needs a backend callback handler. **Why it
matters:** install + first harvest in under 5 minutes for anyone.

### Ask / chat surface (v4 big bet)
A `/ask` route with a chat input bound to the user's BYOK Claude /
OpenAI key. The Reasoner tier (which doesn't exist yet) prepares
context bundles from the brain for each turn. Citations link back to
source notes. **Why it matters:** this is the actual product thesis —
*"compilation over retrieval"* — paying off. The dashboard becomes the
surface where the user reaps that investment.

### Entity pages
Compiled pages per person / project / product. Sarah Chen's page:
summary, recent mentions, action items, related projects, every note
that touches her. Same structure for "Project Atlas" or "Acme Corp."
Needs entity resolution in the compiler. **Why it matters:** the
question *"what do I know about Sarah?"* gets an answer, not a list of
grep matches.

### Context-export bundles
One-click: *"Copy a markdown bundle of every note about Project Atlas,
suitable for pasting into Claude, an email, or a deck."* The
deliverable-generation problem reframed: Mnemify provides the
context, the user (or their AI) writes the deliverable. **Why it
matters:** unblocks downstream work without the dashboard becoming a
writing tool.

---

## Smaller-but-real wins for v2.1

These didn't make it into v2 but are quick follow-ups:

- **Drag-folder-to-input** in the Obsidian wizard (browsers expose the
  *name* of a dropped folder via DataTransfer; combined with our
  `/browse-dir` endpoint, it can resolve to a full path). Native feel
  without the browser modal.
- **Detect doubled-up tilde** in path inputs (`~/Users/<name>/…`) and
  offer to auto-fix. Today the error message is descriptive but the
  fix is manual.
- **Sticky filter chips** in Documents: when filters are active, show
  them as removable chips above the table.
- **Empty-source-card CTA** when no sources connected: replace the
  `null` activity feed and zeroed-out sources panel with a single
  "Connect your first source" card on Home.

---

## Things explicitly NOT to build (per planning docs)

- A native Mnemify chat with its own model. **BYOK only** — users
  plug in the AI they already use.
- Deliverable generation (drafting decks, emails). Too broad; users
  already have tools. Mnemify provides the context bundle.
- Multi-workspace / team features in v3. **Single-user local-first is
  the v3 ceiling.**
- Mobile app. Web is responsive; revisit if mobile crosses 20% of
  traffic.
- Graph compression. Packets are small (markdown); revisit at 10+ GB.

---

## Decision principles when picking the next thing

1. **Every feature must serve one of the four jobs.** If it doesn't,
   it's not for v3.
2. **Quick wins ship first.** ⌘K, onboarding, the trust trio
   (export / reset / audit). These compound — they make every other
   feature easier to use.
3. **Real-data swap is gating.** Most v4 features (chat, entity pages,
   context bundles) assume the dashboard reflects real harvest data.
   Ship that swap before betting on big features.
4. **Anthropomorphic copy is free.** Slip it in everywhere; it doesn't
   cost engineering time but compounds emotional payoff.
