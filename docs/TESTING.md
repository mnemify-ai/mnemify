# Mnemify — End-to-End Testing Guide

A manual walkthrough of every frontend surface against the real FastAPI backend. Each section has **what to do**, **what to expect**, and **how to verify it actually landed on disk** when relevant.

Budget: 20–30 minutes for a full pass. Test env is your own machine — real Notion + Confluence APIs.

> **Note (May 2026):** this guide predates a few changes — the connection wizards now live under **Settings → Connections** (the standalone `/connections` route became a tab), there's a dedicated **`/compile`** route, and the old `/graph` placeholder route is gone (the home page *is* the 3D brain map, fed by the compiled terrain). The route paths below are mostly right; where one isn't, the app's nav is the source of truth. The automated test suites (`pytest -q` in `backend/`, `npm test` in `frontend/web/`) are the fast feedback loop — this doc is the human smoke test.

---

## 0 · Prereqs (one-time)

- Python 3.11+ (`python3 --version`) and Node 20+ (`node --version`)
- A Notion internal-integration token — create one at https://www.notion.so/my-integrations
- An Atlassian API token (optional, for Confluence/Jira) — create at https://id.atlassian.com/manage-profile/security/api-tokens
- An `OPENAI_API_KEY` (optional — only the OpenAI compile path needs it; `--ai-mode local` needs nothing)
- Backend deps: `cd backend && pip install -e ".[dev]"`
- Frontend deps: `cd frontend/web && npm install`

The fastest way to bring everything up is `./run.sh --dev` from the repo root (Vite on :5173, proxying `/api/*` to FastAPI on :8783). The two-terminal steps below are the manual equivalent.

---

## 1 · Start the servers

Two processes, two terminals, same repo (or just `./run.sh --dev`).

**Terminal 1 — FastAPI (port 8783):**
```bash
cd mnemify/backend
python3 -m src up --no-browser
```
Expect:
```
Mnemify up on http://127.0.0.1:8783
INFO:     Application startup complete.
```

**Terminal 2 — Vite (port 5173+):**
```bash
cd mnemify/frontend
npm run dev
```
Expect:
```
VITE v8.0.9  ready in …
➜  Local:   http://localhost:5174/
```

Open the Vite URL. It'll proxy `/api/*` to FastAPI on :8783.

**✅ Health check:** `curl http://localhost:5174/api/health` → `{"ok":true,"version":"0.1.0"}`

---

## 2 · Clean slate (first run)

Before you test anything:

- The **footer badge** (bottom-right) should show 🟢 **live backend**. If it's 🟡 **mocked**, you have `VITE_USE_MOCKS=1` set — unset it and restart Vite. If 🔴 **backend offline**, FastAPI isn't running.

**To start from zero (no connections, no harvested data, no Mnemify-owned secrets):**

```bash
cd mnemify/backend
python3 -m src reset
```

This one command wipes:
- `.mnemify/` — all harvested bytes, manifest DB, harvest log
- `.env` — `NOTION_TOKEN`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`, `JIRA_EMAIL`, `JIRA_API_TOKEN` (unrelated keys preserved)
- `mnemify.yaml` — flips every `sources.*.enabled` to `false` (comments + structure preserved)

Leaves untouched: `.mnemify-backup/`, non-Mnemify `.env` entries, yaml comments/ordering.

Flags:
- `--yes` skips the confirmation prompt (for scripts)
- `--keep-env` wipes data + yaml flags but leaves credentials in `.env`

After `reset`, **restart the backend** (Ctrl+C the uvicorn terminal, run `python3 -m src up` again) so it reloads `.env` from disk. Then hard-refresh the browser.

---

## 3 · Connections route — Notion wizard

**Path:** `/connections`

**What to do:**
1. Land on `/connections`. See two live cards (Notion, Confluence) on animated shader backgrounds. Two ghosted cards (Jira, Gmail) marked "Coming soon".
2. Click **Connect** on the Notion card.
3. The wizard modal slides in. Step 1: "Paste your Notion integration token."
4. Click **Open Notion integrations** (opens in a new tab). Create an integration, copy the token, come back.
5. Paste the `ntn_…` token into the field.
6. Click **Test connection**.

**Expected:**
- Button spins, then the whole step body replaces with the **"First synapse formed."** success panel: a glowing orb + three expanding concentric rings + ~14 particles flying outward, workspace name shown below the orb.
- After ~1.2s the wizard slides to Step 2.

**Verify on disk — open a new terminal:**
```bash
grep "^NOTION_TOKEN=" mnemify/backend/.env
```
Should show the token you just pasted. Unrelated keys (CONFLUENCE_*, JIRA_*) are untouched.

```bash
grep -A5 "^  notion:" mnemify/backend/mnemify.yaml
```
Should show `enabled: true`, `token_env: NOTION_TOKEN`. Other source blocks untouched, comments preserved.

---

## 4 · Notion wizard — share pages + scope

**What to do (Step 2 — the gotcha screen):**
1. Screen says "Mnemify can see 0 pages — that's expected."
2. In your Notion browser tab, open any page, click `•••` → Connections → select the Mnemify integration you made.
3. Come back to the wizard and click **Rescan**.

**Expected:**
- Spinner on the Rescan button.
- Real-time `GET /api/connections/notion/discover` fires against Notion's `/v1/search`.
- Count updates to however many pages + databases your integration can see.

**What to do (Step 3 — scope picker):**
4. Once count > 0, click **Continue**. You see a tree of pages / databases with checkboxes.
5. Click **Select all** (or individually check a few).
6. Click **Save & finish**.

**Expected:**
- Wizard closes.
- Notion card flips to **Connected ✓**. A one-time on-card animation plays: two expanding gradient rings, 10 particles, a radial glow pulse. Border picks up a subtle indigo + glow-sm shadow. Card copy reads "`N` spaces · ready to harvest".
- Toast: "Notion connected."

**Verify:** `grep -A10 "^  notion:" mnemify/backend/mnemify.yaml` — you should see the scope you picked in the block.

---

## 5 · Connections route — Confluence wizard

**What to do:**
1. Click **Connect** on the Confluence card. Two-step wizard.
2. Step 1: enter base URL (`https://<your>.atlassian.net/wiki`), email, API token.
3. Click **Test connection** → success panel → step 2.
4. Step 2: space picker shows every space you have access to (this is live from `/rest/api/space?limit=50`).
5. Pick 1–2 spaces, Save.

**Expected:** same card-flip animation, toast, and backend write-through.

**Verify on disk:**
```bash
grep -E "CONFLUENCE_(EMAIL|API_TOKEN)=" mnemify/backend/.env
grep -A8 "^  confluence:" mnemify/backend/mnemify.yaml
```
- `base_url` in yaml now matches what you typed (no more `company.atlassian.net` placeholder).
- `space_keys` lists the spaces you ticked.

---

## 6 · Connections route — Disconnect flow

**What to do:**
1. Click **Manage** on the now-connected Notion card.
2. A centered AlertDialog (not the native `confirm()`) asks "Disconnect Notion?".
3. Click **Disconnect**.

**Expected:**
- Toast: "Notion disconnected."
- Card flips back to **Not connected** with the grey shader intensity.

**Verify:**
- `grep "^NOTION_TOKEN=" mnemify/backend/.env` — line is gone.
- `grep -A3 "^  notion:" mnemify/backend/mnemify.yaml` — `enabled: false`.
- Other source configs + other env keys untouched.

Reconnect Notion before continuing with §7+.

---

## 7 · Harvest route — live run

**Path:** `/harvest` (reachable from the top-right "Start Harvest" CTA, the dashboard Run-one-now link, or ⌘K → "Start a harvest").

**What to do:**
1. Make sure you have ≥1 source connected (or all the next steps error out cleanly).
2. Click **Start Harvest** in the top nav.

**Expected:**
- Route changes to `/harvest`.
- 3D `<HarvestFlow>` canvas fills the top third of the screen: source nodes on the left with gentle rotation, central violet Mnemify core, particles streaming along Bézier curves as real docs arrive.
- Each successful doc → white/blue/other-colored particle. Failed doc → red particle.
- Per-source progress tiles (Notion: 43/128 · 4.2/s · ETA 17s). Bars animate smoothly.
- Live log tail underneath: newest on top, color-coded (green = harvested, red = error, grey = skipped), showing real doc titles from your Notion/Confluence.
- **Pause** and **Cancel** buttons in the top right.

**Verify on disk while running:**
```bash
ls mnemify/backend/.mnemify/raw/notion/
ls mnemify/backend/.mnemify/raw/confluence/
```
Directories fill with real harvested bytes.

```bash
tail -f mnemify/backend/.mnemify/harvest-log.jsonl
```
Real JSONL events streaming — these are the same events the UI log tail is reading (via SSE on `/api/harvest/stream`).

**Test cancel mid-run:** click **Pause** → emission halts; **Resume** → continues; **Cancel** → orchestrator stops, state becomes "cancelled", no completion summary.

**On completion:**
- A summary card slides in: *"N memories formed in Xs"*.
- CTAs: **View documents** (→ /documents) and **Run again** (fresh run).
- If docs failed, a rose-tinted "N documents need attention" table appears with per-row **Retry** buttons.

**Verify:**
```bash
python3 -m src status
```
Should show a manifest stats block with real counts matching the UI summary.

---

## 8 · Dashboard

**Path:** `/`

**Expected:**
- Headline "Your brain holds **N** memories." where N spring-animates up from 0 to the real count.
- 3D `<NeuralHero>` sphere below the headline: ~150–200 nodes on a Fibonacci sphere (one per harvested doc), edges between same-source/space docs, bloom post-processing glow, slow rotation + cursor parallax.
  - Hover the hero area — the sphere drifts toward the cursor.
  - If you haven't harvested yet, you see the **dormant state**: 12 dim pulsing nodes + the same copy.
- Four stat tiles count up: Documents, Total size, Sources, Last harvest.
- **Harvested over time** sparkline — real SVG line chart, gradient stroke, 14-day window.
- **By source** donut — real per-source doc counts, brand-colored segments.
- **Recent harvests** feed — last 6 runs pulled from `/api/harvest/history` (reads `harvest-manifest.db` directly).

**Verify:** the dashboard numbers match `python3 -m src status`.

---

## 9 · Documents — Table view

**Path:** `/documents` (also ⌘K → "Go to Documents").

**What to do:**
1. You should see a virtualized table of every harvested doc.
2. Filter by source: click **Notion** pill.
3. Search: type a doc title you recognize (e.g., "runbook", "roadmap").
4. Click any row.

**Expected:**
- Columns: Title (with source icon), Space, Type, Size, Updated, Harvested.
- TanStack Table + react-virtual handles the list at 44px row height — smooth scroll even with thousands of rows.
- Filter pill + search both narrow the list immediately.
- Row click slides a **right-side DocDrawer** in:
  - Source icon + space + type chips
  - Metadata grid: Size, Updated, Harvested, ID
  - Rendered markdown preview (headings, bullets, italics) of the doc's raw content, read from `.mnemify/raw/`
  - Footer shows `.mnemify/raw/` and a Copy ID button
- Press **Escape** → drawer closes.

---

## 10 · Documents — Tree view

**Path:** `/documents/tree` (tab switcher at the top of `/documents`).

**Expected:**
- Hierarchy: source → space → page, each layer expandable.
- Default: source layer is open.
- Click a space → list of its pages animates open.
- Click a leaf → same `<DocDrawer>` opens.
- Empty-state message if no docs yet.

---

## 11 · Settings route

**Path:** `/settings`.

**What to do and expect:**

**Data location:** Banner shows `~/Mnemify/.mnemify/` with a working **Export zip** button (currently a toast placeholder — real zip export lands with backend polish).

**Motion & sound — toggles:**
- Toggle **Reduce motion ON**.
- Navigate back to the Dashboard. `NeuralHero` freezes to a static gradient orb. HarvestFlow (if running) shows static source dots + arrow + core — no motion. `AnimatedCounter`s snap instantly. Shader backgrounds on connection cards turn into plain CSS gradients.
- Toggle **OFF** → everything resumes animating immediately (no reload needed — the pref is broadcast via a custom event that `useReducedMotion` listens for).

**Harvest sound:** toggle on/off (the actual chime asset is a later polish item — toggle just persists the pref).

**Sources:** read-only display of per-source concurrency + filters (editing in a later phase).

**Reset:**
- Click **Disconnect everything & reset**. Branded AlertDialog: "Wipe the brain?".
- **Wipe everything** → toast "Memory wiped. Ready when you are." → redirects to `/connections`. All sources now show Not connected.
- **Verify on disk:**
  - `.env` — all Mnemify keys (`NOTION_TOKEN`, `CONFLUENCE_*`, `JIRA_*`) removed. Unrelated keys preserved.
  - `mnemify.yaml` — every `sources.X.enabled` set to `false`, structure + comments otherwise unchanged.
  - `.mnemify/raw/`, `.mnemify/normalized/`, `.mnemify/harvest-manifest.db`, `.mnemify/harvest-log.jsonl` — gone.
  - `.mnemify-backup/` (if you made one) — untouched.

---

## 12 · Graph route

**Path:** `/graph`.

**Expected:**
- Full-viewport 3D force-directed graph (react-force-graph + three.js).
- Sidebar filters for communities, relation types, confidences (from the original graph explorer — still wired to `/graph.json` static file).
- No nav chrome overlap with the canvas (main layout is full-bleed on this route).
- This surface is the Phase 1 placeholder — it'll ingest real data once the compiler tier ships.

---

## 13 · Phase E polish — keyboard shortcuts

**Try each:**
- **⌘K** (or Ctrl+K) — opens the **CommandMenu** palette. Type "doc" → filtered list narrows. Arrow keys navigate, Enter runs, Esc closes.
- **⌘N** — triggers Start Harvest from anywhere (routes to /harvest and kicks off the run if idle).
- **?** — opens the **Shortcut cheatsheet** dialog listing every binding.
- **Esc** — closes any open dialog / drawer / palette.

The ⌘K pill is visible in the top nav next to Start Harvest. Clicking it also opens the palette.

---

## 14 · Phase E polish — onboarding checklist

**Path:** `/connections` or `/`, with **no connections yet**.

**Expected:**
- A small floating widget appears in the bottom-left: **Get started** with three items:
  1. Connect a source
  2. Pick what to ingest
  3. Run your first harvest
- As you complete each step, the numbered circle flips to a green checkmark and the label strikes through.
- When all three are done, the checklist disappears.
- The **X** button in the top-right of the widget dismisses it permanently (persisted to `localStorage.mnemify.onboarding.dismissed`). Reset via Settings → Reset unsets this so new-user state returns.

---

## 15 · Phase E polish — performance guardrails

Each 3D Canvas in the app pauses itself when you can't see it:

- **NeuralHero + HarvestFlow**: switch to a different tab or minimize the window. They stop rendering (`frameloop="never"`). Come back — they resume immediately.
- **ShaderCards** (on Connection cards): scroll them off-screen. They pause via IntersectionObserver. Scroll back — they resume.
- Reduced-motion also bypasses the Canvases entirely, using static CSS gradients.
- Low-tier devices (detected via `navigator.hardwareConcurrency < 4` or `navigator.deviceMemory < 4`) auto-reduce particle counts.

No UI to verify this directly; inspect the DOM in DevTools to confirm Canvas elements exist where expected.

---

## 16 · Edge cases worth hitting once

- **Bad Notion token:** paste garbage → Test connection. Expect a red toast "Couldn't validate that token." with a reason pulled from the Notion API response. No write to `.env`.
- **Bad Confluence base URL:** type something malformed → Test. Same shape of failure.
- **Notion integration with zero pages shared:** rescan repeatedly. Count stays at 0. Button remains disabled on Continue.
- **Concurrent harvest triggers:** click Start Harvest twice. Second one is a no-op (`already running` from the backend).
- **Mid-harvest reload:** harvest running → hard-refresh the page. The UI reconnects to the SSE stream via `/harvest/stream` and receives the current-state snapshot event so you pick up where you left off.
- **Backend offline:** kill FastAPI. Footer badge turns 🔴. Connect flows surface an ApiError. Dashboard shows empty state without crashing.
- **MSW mode fallback:** `VITE_USE_MOCKS=1 npm run dev` — footer badge 🟡. All the fixture fakes work without a backend. Handy for UI-only work.

---

## 17 · Cleanup

If you want to leave the machine tidy after testing:

```bash
# Stop both servers (Ctrl+C in each terminal)
# Purge the test harvest:
rm -rf mnemify/backend/.mnemify
# Optional — strip test credentials:
sed -i '' '/^\(NOTION_TOKEN\|CONFLUENCE_EMAIL\|CONFLUENCE_API_TOKEN\)=/d' mnemify/backend/.env
# If you moved the original backup aside and want it back:
mv mnemify/backend/.mnemify-backup mnemify/backend/.mnemify
```

---

## Quick test matrix (spot-check at-a-glance)

| Surface | Path | Key things that must work |
|---|---|---|
| Health | `/api/health` | 200 + `{ok:true}` |
| Connections list | `/connections` | Shader cards, live status, wizard opens |
| Notion wizard | modal from `/connections` | Real validate → burst → real rescan → scope → save |
| Confluence wizard | modal from `/connections` | Real validate → real space list → scope → save |
| Disconnect | AlertDialog from Manage | `.env` + yaml updated correctly |
| Harvest | `/harvest` | 3D flow, progress, log, pause/cancel, completion summary |
| Dashboard | `/` | NeuralHero, stat counters, sparkline, donut, activity |
| Documents (table) | `/documents` | Virtualized table, filter, search, drawer |
| Documents (tree) | `/documents/tree` | Expand → drawer |
| Settings | `/settings` | Reduce-motion toggle kills animation live, Reset works |
| Graph | `/graph` | Full-bleed force graph still renders |
| ⌘K | anywhere | Palette opens, arrow + enter works |
| ? | anywhere | Shortcut cheatsheet |
| ⌘N | anywhere | Starts a harvest |
| Onboarding | `/connections` with no conns | Widget appears bottom-left, ticks off live |
| Tab-hidden perf | any 3D | Canvas pauses when tab hidden |

---

## If something breaks

1. **Dev server boot splash stuck or red error box visible:** check the browser Console (⌘⌥I → Console tab) and paste the first red line.
2. **3D canvas shows "AFRAME is not defined":** regression we already fixed once — `import ForceGraph3D from "react-force-graph-3d"` (not the umbrella package).
3. **Dialog opens in the bottom-right:** regression of the transform-based centering animation. `DialogContent` must use `data-[state=open]:animate-fade-in`, never `animate-slide-up`.
4. **Mock worker intercepting real API:** `main.jsx` auto-unregisters stale MSW workers on load, but Cmd-Shift-R in the browser guarantees it. Or manually: DevTools → Application → Service Workers → Unregister.
5. **Credentials not persisting after save:** verify the FastAPI logs (Terminal 1) actually show the POST requests coming through. If not, Vite proxy isn't pointing at :8783 — check `vite.config.js`.
