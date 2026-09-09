# Mnemify Dashboard — Technical Reference

The React app (`frontend/web/`). For a one-page overview + how to run it, see
the repo `README.md`; for the backend, `docs/BACKEND.md`; for the end-to-end
data flow, `docs/TECHNICAL.md`. If something here disagrees with the code in
`web/src/`, the code is right and this file is stale — update it.

---

## Stack

- **React 18 + Vite 5 + TypeScript** (strict, `noUnusedLocals`, `noUnusedParameters`)
- **Tailwind CSS 3** with a CSS-variable-driven cream / pastel palette
- **React Router v6** for routing (`createBrowserRouter`)
- **TanStack Query v5** for all REST data (the brain map, connections, harvest/compile state)
- **TanStack Virtual** for the documents table and the live log tail
- **Three.js + @react-three/fiber + drei + @react-three/postprocessing** for the BrainMap (bloom + N8AO)
- **Zustand** per BrainMap mount for the 3D scene's local state
- **vaul** for right-side drawers; **@radix-ui/react-dialog** for centered modals
- **sonner** for toasts, **lucide-react** for icons, **date-fns** for relative times
- **class-variance-authority + tailwind-merge + clsx** for the component variant system

---

## Folder layout

```
web/src/
├── main.tsx                Mounts Router + QueryClient + BrainDataProvider + Sonner + theme.css
├── brainMap/               Self-contained 3D module — drop-in component
│   ├── BrainMap.tsx        Public component (see "BrainMap props" below)
│   ├── chrome/             Header, Sidebar, Legend, MiniMap, StatsPanel, Breadcrumb, TimeScrubber
│   ├── scene/              R3F primitives: HexField, Arcs, Beams, RegionLabels, TagLabels, CameraAnimator, Scene
│   ├── data/               useRenderData, useNotes
│   ├── store.ts            createBrainMapStore + Provider + useBrainMapStore
│   ├── types.ts            RenderData, RegionEntry, Arc, Highlights, Note, NotesFile
│   ├── util/               colorRamp, hexGeometry
│   └── input/              useEscapeHandler
└── app/                    Dashboard shell + everything else
    ├── routes.tsx          createBrowserRouter — 6 routes
    ├── theme/index.css     CSS vars + @tailwind directives + grain + glass-panel utilities
    ├── layouts/            DashboardLayout (TopBar + Outlet), PageShell
    ├── pages/              HomePage, ConnectionsPage, HarvestPage, CompileReportPage, DocumentsPage, SettingsPage
    ├── components/
    │   ├── ui/             Button, Card, Badge, Pill, Separator, Dialog, AlertDialog, SideDrawer
    │   ├── wizards/        WizardModal, ScopeListPicker, NotionWizard, ConfluenceWizard, ObsidianWizard
    │   └── (page-level)    TopBar, BrandMark, LastCompiledPill, MinimizedHarvestPill,
    │                       FloatingSourcesPanel, ActivityFeed, TagProvenanceDrawer, DocTable,
    │                       DocDrawer, DocFiltersPanel, ConnectionCard, LiveStatusBadge,
    │                       CompileStatsGrid, HighlightsPanel, HarvestProgressBar, LiveLogTail,
    │                       CompletionSummary, HarvestHistoryList, FolderBrowser,
    │                       RegionBreadcrumb, SourceBadge
    ├── data/               BrainDataProvider, indexes, selectors, types
    ├── api/                client, keys, connections, harvest
    ├── sse/                useHarvestStream (EventSource wrapper)
    └── lib/                cn, queryClient, relativeTime, formatEta, useTagParam,
                            useDocFilters, useThemeMode
```

---

## Where the data comes from

Everything is live backend data — there's no bundled demo dataset any more.
Two layers:

### The compiled brain map (BrainDataProvider)

`app/data/BrainDataProvider.tsx` fetches `GET /api/terrain/render-data` (the v3
hex render-data the compiler wrote to `.mnemify/`) once at boot — a `404`
means "nothing's compiled yet" and the home page shows `BrainEmptyState`. It
also pulls `GET /api/terrain/notes`, builds memoized indexes
(`regionsById`, `regionPathById`, `regionByTagId`, `topLevelRegionByTagId`,
`topLevelRegionByRegionId`, `tagIdToIdx`, `tagHeights`, `arcsByTagId`,
`notesByTagId`, `notesByRegionId`, `notesByRegionSubtree`, `isolatedTagIds`),
and exposes them through React context. The 3D `BrainMap`, the
`TagProvenanceDrawer`, and the compile report all read from here.

`app/data/selectors.ts` exposes `useTagInfo` / `useNotesForTag` (against those
indexes) and the `tagIdToLabel` slugifier (`tag.ocr-accuracy` → `"OCR Accuracy"`).

> The `brainMap/` module is self-contained: `<BrainMap>` defaults `dataUrl` to
> `/api/terrain/render-data` and `notesUrl` to `/api/terrain/notes`, so it
> works standalone. `HomePage` passes `apiUrl(...)`-resolved overrides so the
> `VITE_API_BASE_URL` build-time setting (if any) is honoured.

### Live REST + SSE (TanStack Query)

`app/api/*.ts` wraps the FastAPI endpoints under `/api/` (Vite proxies to
`localhost:8783` in dev; in prod the same backend serves the built SPA, so
`/api/*` is same-origin). Hooks:

| Hook | Endpoint | Purpose |
|---|---|---|
| `useConnections` | `GET /api/connections` | Source rows with `{source, status, workspace_name, last_harvest_at, doc_count}` |
| `useValidateNotion` | `POST /api/connections/notion/validate` | Test a pasted token |
| `useValidateConfluence` | `POST /api/connections/confluence/validate` | Test base URL + email + API token |
| `useValidateObsidian` | `POST /api/connections/obsidian/validate` | Test a vault path (added for this dashboard) |
| `useDiscoverNotion` | `POST /api/connections/notion/discover` | List accessible pages + databases |
| `useDiscoverConfluence` | `POST /api/connections/confluence/discover` | List spaces |
| `useBrowseDir` | `POST /api/connections/browse-dir` | Folder picker for Obsidian (added for this dashboard) |
| `useSaveNotion / Confluence / Obsidian` | `POST /api/connections/{src}/save` | Persist credentials + scope |
| `useDisconnect` | `DELETE /api/connections/{src}` | Remove credentials + disable in YAML |
| `useHarvestCurrent` | `GET /api/harvest/current` | Polled state (5s while running) |
| `useHarvestHistory` | `GET /api/harvest/history` | Last 20 runs |
| `useStartHarvest` | `POST /api/harvest` | Body: `{sources, force_full?, scope?}` |
| `useCancelHarvest` | `POST /api/harvest/cancel` | |
| `useHarvestStream(enabled)` | `EventSource(/api/harvest/stream)` | Live harvest progress + logs |
| `useTerrainCompile*` / `useCompileStream` | `POST /api/terrain/build`, `EventSource(/api/terrain/stream)` | Compile lifecycle + live progress |
| `useTerrainReport` | `GET /api/terrain/report` | Lightweight "what's compiled" summary (stats, highlights, last run) |
| `useDocuments` / `useDocumentStats` | `GET /api/documents*` | The harvested-docs table + counts |

`ConnectionCard` joins a source's live `/api/connections` row (status,
`workspace_name`, `doc_count`, `last_harvest_at`) with a re-harvest action and
the manage-scope / filter editors — all live; there's no mock snapshot any more.

---

## Routes

```
/                   HomePage          (fullscreen BrainMap + floating overlays)
/connections        ConnectionsPage   (source cards + Connect wizards + Disconnect AlertDialog)
/harvest            HarvestPage       (live SSE view; history when idle)
/compile            CompileReportPage (stats + highlights)
/documents          DocumentsPage     (virtualized table + filters + drawer)
/settings           SettingsPage      (snapshot info + theme + data source URLs)
*                   → /
```

URL-owned state (so all of it survives reloads and is bookmarkable):

- `/?tag=tag.foo` → opens `TagProvenanceDrawer`
- `/connections?connect=notion|obsidian|confluence` → opens the matching wizard
- `/documents?source=notion&region=products&tag=…&q=…&since=30d` → table filters
- `/documents?id=n-007` → opens `DocDrawer`

---

## Pages — what each one is

**HomePage.** Fixed-positioned BrainMap (z0) under floating panels:
TopBar (z40) with brand + nav + `MinimizedHarvestPill` + `LastCompiledPill`,
`FloatingSourcesPanel` top-left (z10), `ActivityFeed` bottom-right (z10),
and `TagProvenanceDrawer` on the right (z30) when `?tag=` is set.

**ConnectionsPage.** Three live-capable cards first (Notion / Obsidian /
Confluence) with Connect or Re-harvest buttons + Disconnect link. Then
three Coming-soon cards (Jira / Gmail / Slack) derived from the mock
dataset's sources but lacking backend support. Header has a "Harvest
all enabled" CTA (disabled at zero connected). Bottom card lists
deferred v3 features. Disconnect goes through an `AlertDialog`.

**HarvestPage.** Four state branches keyed off
`useHarvestCurrent().data?.status`:

- *idle + no history* → empty state with "Connect a source" CTA
- *idle + history* → `HarvestHistoryList` (expandable rows; per-doc
  logs are not exposed yet — note in footer says they land in v3)
- *running* → 4-tile hero (Harvested / Rate / ETA / Sources count),
  per-source `HarvestProgressBar`s with "Listing…" / "Harvesting" /
  "Complete" pills, `LiveLogTail` (200-line ring buffer, virtualized,
  "Jump to latest" pill when user scrolls), and a Cancel button
- *complete / cancelled* → `CompletionSummary` with anthropomorphic
  *"Your brain learned N new memories"* copy + per-source breakdown +
  three CTAs (View documents / Re-run / Back to brain)

While running and the user navigates away, `MinimizedHarvestPill`
appears in the TopBar with "Harvesting · 43/128" and a pulse dot;
clicking it returns to `/harvest`.

**CompileReportPage.** 5-tile stats grid (Regions / Tags / Notes /
Sources / Arcs) + 4-column `HighlightsPanel` (God / Bridge / Trending /
Isolated). Each chip is clickable and navigates to `/?tag=<id>` to open
the provenance drawer on Home. Footer shows `render-data.generatedAt`.

**DocumentsPage.** Sticky left filter rail (search input, source
multi-select, top-region radio, tag typeahead, date window) +
virtualized `DocTable` with column sorting on Title / Source / Updated /
Words. Row click opens `DocDrawer`, which renders the note metadata,
clickable tag chips (primary tag in magenta, others in lavender), a
"View source" link to the `sourceUrl`, and notes about what v2 doesn't
yet do (full content rendering is excerpt-only until v3).

**SettingsPage.** Snapshot card (read-only render-data metadata), Theme
toggle (Cream / Ink, persists to `localStorage.mnemify:theme`), Data
source card with the two file URLs + sizes (HEAD request for
`Content-Length`) + Reload button, "Coming in v2" deferred list.

---

## The BrainMap module

`brainMap/BrainMap.tsx` is a self-contained R3F-powered component that
owns its own data fetch, WebGL scene, and Zustand store per mount. The
dashboard imports it and feeds it props to integrate with the router's
URL state.

**Public props** (`BrainMap.tsx:21–60`):

| Prop | Type | Behavior |
|---|---|---|
| `dataUrl?` | `string` | v3 render-data URL (default `/api/terrain/render-data`) |
| `notesUrl?` | `string` | notes-registry URL (default `/api/terrain/notes`) — only used by the internal Sidebar; ignored when `renderTagPanel` is defined |
| `focusRegionId?` / `onFocusChange?` | `string \| null` | Controlled scope drill-down |
| `selectedTagId?` / `onTagSelect?` | `string \| null` | Controlled tag selection |
| `renderTagPanel?` | render-prop | When defined, suppresses the internal Sidebar; host provides its own panel |
| `hideHeader / hideBreadcrumb / hideLegend / hideMiniMap / hideStatsPanel / hideTimeScrubber?` | `boolean` | Suppress individual chrome pieces |

The dashboard uses `hideHeader`, `hideBreadcrumb`, `hideStatsPanel` + a
custom `renderTagPanel` to mount its own `<TagProvenanceDrawer />`.

**Echo-loop guard.** The controlled-prop bridges
(`useControlledFocusBridge`, `useControlledTagBridge`) use a ref-based
pattern: each effect (prop → store and store → prop) tracks the last
value it synced/fired with via `useRef`, so an update never bounces
back where it came from. This is the right fix for the classic
controlled/uncontrolled sync ping-pong.

**Hierarchy hover + labels (`knowledgeMap/`).** The map is browsed one
level at a time, and all hover feedback resolves to that level via
`util/hoverRegion.ts`: `resolveHoverChild()` maps the hovered hex's LEAF
region to the top-level region at the map root, or to the immediate child
of the focused region once inside one (unrelated terrain and the focused
region's own hexes resolve to nothing). `useHoverRegion()` merges that
with `legendHoverIdx` (sidebar row / on-map label under the cursor) into
one answer that drives, in lock-step:

- `scene/HexField.tsx` — brightens the whole footprint of the resolved
  region (`instancesByRegion`, a hex filed under every ancestor).
- `chrome/RegionsList.tsx` / `chrome/RegionDetail.tsx` — the matching row
  lights and scrolls into view; hovering a row lights the terrain.
- `scene/RegionLabels.tsx` — `buildLevelLabels()` produces the label set
  for the current level: top-level regions at the root; inside a region,
  its children plus the region's own lifted title. Hovered / current
  labels are forced on; with ≤ 2 children every child is forced;
  otherwise the zoom-scaled, overlap-tested budget applies.
- `chrome/RegionHoverPreview.tsx` — after 200 ms on terrain, a
  cursor-anchored card with name · notes · sub-regions · first sentence
  of the attention summary. Yields to `HexTooltip` on tag spires.

Hover never navigates or moves the camera; clicks keep HexField's
one-step drill-down.

---

## Wizards

All three wizards share `WizardModal` (centered Radix Dialog, 560 px,
magenta step-indicator dots) and an important UX rule:

> **Continue is disabled until a successful Test pass.** The moment any
> credential field changes after a test result, validation resets to
> `idle` and Continue goes back to disabled. This forces a re-Test
> before saving anything stale.

Each wizard implements this via `update{Token,VaultPath,BaseUrl,…}`
helpers that wrap `setX` and clear `validated` when not already idle.

**NotionWizard** (3 steps). Paste token + Test → share-pages gotcha +
Rescan → `ScopeListPicker` over pages+databases. Save toast:
*"First synapse formed."*

**ConfluenceWizard** (2 steps). Base URL + email + token (with Test) →
`ScopeListPicker` over spaces (keys as primary, names as subtitle —
following the "keys not names" guardrail from the original Atlassian
plan).

**ObsidianWizard** (2 steps). Vault path with Validate → optional
watch-folders. Step 1 has a **Browse…** button that opens
`FolderBrowser` — a backend-driven directory browser. Browsers can't
expose absolute filesystem paths to JavaScript for security reasons,
so the directory listing happens server-side via
`/api/connections/browse-dir`. Folders containing `.obsidian/` are
highlighted with a sage "vault" badge; the footer's "Use this folder"
button is enabled only when the *current* directory is itself a vault.

---

## Harvest live view — SSE wire protocol

`useHarvestStream(enabled)` opens an `EventSource` against
`/api/harvest/stream` when `enabled === true`. The backend sends real
events as default `message` events with a `type` discriminator in the
JSON body (only `ping` heartbeats are named events). So the hook
listens to `onmessage` and switches on `parsed.type`:

```
{type: "snapshot",  state: {status, sources, summary}}              // always first
{type: "progress",  source, done, total, already_harvested, rate_per_sec}
{type: "log",       level: "info", source, doc_id, title, msg, ts}
{type: "error",     level: "error", source, doc_id, title, msg, ts}
{type: "complete",  summary: {harvested, failed, skipped, seconds}, ts}
```

Logs ring-buffer at 200 entries (oldest dropped). Reconnect uses
exponential backoff: 1 → 2 → 4 → 8s, cap 30s; the backoff resets on
the first successful message. On `complete`, the hook invalidates the
`['connections']`, `['harvest','current']`, `['harvest','history']`
query keys so the rest of the app picks up post-run state.

`HarvestPage` prefers the stream's state while connected, falling back
to `useHarvestCurrent` (polled at 5s while running) otherwise.

---

## Theme + design system

CSS variables in `app/theme/index.css`. Tailwind colors map directly:
`bg-cream` resolves to `rgb(var(--c-bg) / <alpha-value>)`, etc.

```
--c-bg:       245 239 232   #F5EFE8   page background (cream)
--c-bone:     240 232 220             elevated surfaces (cards)
--c-lavender: 232 220 224             callout / secondary surfaces
--c-rose:     200 132 162             error / destructive
--c-magenta:  142 44 95     primary accent, focus rings, CTAs
--c-sage:     110 130 92               success / live status
--c-ink:      25 19 22                 body text
--c-muted:    74 64 70                 secondary text
--c-line:     25 19 22                 hairline borders (with low alpha)
```

`html.dark` flips them to a dark palette. The BrainMap itself stays
cream — its WebGL palette is baked into `render-data.json`.

**Typography.** Serif (Times / Georgia) for display + body, Inter for
nav and small UI, JetBrains Mono for IDs + technical values + token
fields.

**Motion.** `prefers-reduced-motion: reduce` is honored globally via
the `@media` block at the bottom of `theme/index.css`. The pulsing
"Harvesting" pill animation respects it through Tailwind's
`animate-pulse`.

**Component variants** use `class-variance-authority` (see `Button.tsx`,
`Badge.tsx`). Composable className merging via `cn()` (clsx +
tailwind-merge).

---

## Vite proxy

`vite.config.ts` proxies `/api/*` → `http://localhost:8783`. For SSE
specifically, the `configure` callback sets `Cache-Control:
no-cache, no-transform` and `X-Accel-Buffering: no` headers on the
`/harvest/stream` response so intermediaries don't buffer the event
stream.

---

## Things to know if you're touching the code

- **No `App.tsx`.** `main.tsx` mounts the router directly — there's no
  intermediate App component to add providers to. Add new providers to
  `main.tsx`.
- **BrainMap's per-mount store is intentional.** Use the controlled
  props (`selectedTagId` + `onTagSelect`) to integrate with route
  state. Don't reach into the store from outside the `brainMap/`
  module.
- **Documents filters are URL-serialized**, including the open
  drawer (`?id=…`). Add a new filter by extending `useDocFilters` and
  the `applyDocFilters` reducer.
- **The brain map's data is the *compiled* terrain** served at
  `/api/terrain/render-data` — there's no bundled demo dataset and no
  `frontend/scripts/` bake step any more (the v3 hex bake is a backend
  module, `backend/src/terrain/_bake_v3.py`, run during compile).
- **The wizards reset validation on every input change.** Don't break
  this — it's how we prevent stale "ok" results from leaking through
  to Save.
