# Recent Changes — post-harvest visibility, author attribution, compile nudge

> Added in v0.8. Answers roadmap job #2 ("What's new since I last looked?"):
> after a harvest — manual or scheduled — the user sees *which* pages were
> added / updated / deleted, *who* changed them, and gets nudged (or the
> system auto-triggers) to compile them into the map.

---

## The core idea: "since last compile"

The whole feature hangs on one boundary: **the completion time of the last
successful terrain compile** (`terrain_runs.completed_at` in
`.mnemify/terrain.db`, read via `TerrainStore.get_last_compile_time()`).

Everything harvested *after* that boundary is, by definition, **knowledge the
map does not contain yet**. That framing drives every surface:

- pending changes → "your map is behind" → compile → boundary moves → count
  drops to zero. No per-user "seen" state to maintain server-side; compiling
  *is* the acknowledgement.
- The endpoint also accepts an explicit ISO timestamp for clients that want
  their own watermark (e.g. a future "since I last looked" inbox).

## Data flow

```
harvest run
  └─ manifest.upsert_document() classifies each doc: new | updated | unchanged
  └─ HarvestLogger appends per-doc JSONL to .mnemify/harvest-log.jsonl
        {"action":"harvested", "change":"new"|"updated", "source","id","title","ts",...}
        {"action":"deleted_at_source", ...}
  └─ documents.metadata JSON stores author fields per source

GET /api/changes?since=last_compile        (backend/src/api/routes_changes.py)
  1. resolve boundary (terrain.db, or the passed ISO timestamp)
  2. HarvestLogger.read_log(since=boundary) — keep harvested / deleted_at_source
  3. dedupe by (source, id): latest entry wins; a doc first seen as "new"
     inside the window stays "new" even if later re-harvested as "updated";
     created-then-deleted collapses to "deleted"
  4. join each row against the manifest for author / last editor / url / space
  5. return { boundary, summary{new,updated,deleted,by_source}, changes[],
              truncated, compile_running, harvest_running,
              last_harvest_time, schedule_enabled }
```

`last_harvest_time` is `MAX(completed_at)` across all sources' harvest runs
(`HarvestManifest.get_last_harvest_time_any()`); `schedule_enabled` is true
when any source has an enabled cron schedule in `mnemify.yaml`. Both feed
the harvest nudge below.

No new harvest-time bookkeeping was required — the JSONL log and the
manifest's metadata column already carried the raw material; the endpoint is
a read-side join.

## Author attribution ("who changed this")

Both sources report a **creator** and a **last editor**; we keep both, under
the same keys, so downstream code never branches per source:

| key in `documents.metadata` | Confluence | Notion |
|---|---|---|
| `author_name` / `created_by` | `history.createdBy` (creator) | `created_by` (resolved via UserResolver) |
| `last_modified_by` | `version.by` (last editor) | `last_edited_by` (resolved name) |
| `last_modified_by_id` | `version.by.accountId` | raw `last_edited_by.id` |
| `created_by_id` | `author_id` (accountId) | raw `created_by.id` |
| `version_message` | `version.message` (edit comment) | — (no public history API) |

Notes:
- Confluence's list endpoint (`expand=version`) already returns `version.by`,
  so the last editor is captured **at list time** too — deleted-later docs
  and skip-path docs still get attribution.
- Notion's public API has no per-revision history; `last_edited_by` +
  `last_edited_time` is the ceiling.
- Attribution preference everywhere in the UI: `last_modified_by` first,
  `author` as fallback ("edited by X" beats "created by X" for a change feed).
- Exposure: `/api/documents` rows carry `author` + `last_modified_by`;
  compiled notes (`/api/terrain/notes`) carry `author` + `lastModifiedBy`
  (set only when it differs from the creator — see `_build_notes()` in
  `terrain/pipelines/compiler.py`); `/api/changes` rows carry both.

## Compile nudge vs auto-compile

Setting: `auto_compile_after_harvest` in the `compile:` block of
`mnemify.yaml` (default **false**), surfaced via `GET/PATCH
/api/settings/compile` and a toggle in Settings → Compile.

- **Off (default):** after a successful harvest the UI nudges —
  - the harvest completion page (`CompletionSummary`) lists the changed pages
    with attribution + a "Compile now" button;
  - a global toast fires from the always-mounted `TopBar` watcher with a
    Compile action (covers scheduled harvests while the user is elsewhere);
  - an amber "N changed" pill stays in the TopBar until a compile runs.
- **On:** `orchestrator._finalize()` (harvest end-of-run) schedules
  `start_compile()` as a fire-and-forget task — only when the run completed
  (not cancelled) and harvested > 0. `start_compile` keeps its own guards
  (refuses mid-harvest / mid-compile); a refusal publishes an `info` event on
  the harvest bus and the UI falls back to the manual nudge. The scheduler
  needs no changes — scheduled runs flow through the same `_finalize()`.

## Offering a harvest (stale-data nudge)

A daily scheduled harvest is deliberately the change-detection mechanism:
after the first cold sync, `_fetch_one` skips unchanged docs **before**
downloading anything (version-vs-manifest compare), so a warm run costs a
handful of listing calls and only pulls genuinely new/changed pages. No
separate "peek" endpoint is needed.

When the last completed harvest is older than 24h (`STALE_HARVEST_MS` in
`app/lib/briefing.ts`), the Home briefing card offers one:
"Last harvested 2d ago — check your sources for new info?" with a
**Harvest now** action and — when no schedule is enabled — a
"Harvest every morning →" link to Settings → Schedules. Rules live in
`computeHarvestNudge` (pure, unit-tested): suppressed while a harvest runs,
while uncompiled changes exist (the compile ask wins — never two asks), and
for 24h after dismissal (localStorage `mnemify.harvestNudge.snoozedUntil`).

When the last harvest is *recent* (< 12h), the pending line switches to
harvest-anchored framing: "Harvested 3h ago · 4 new · 2 updated — not on
your map yet" — this is the morning-arrival moment after a scheduled run.

### Idle-tab detection

Scheduled harvests can start **and** finish while nobody is watching, so:

- `useChanges` refetches every 60s (visible tabs only) and on window focus;
- the TopBar watcher polls `/api/harvest/current` at a 60s idle heartbeat
  (5s while running) and keys the completion toast on **`finished_at`
  transitions**, not on observing a `running → complete` status pair — a
  run that finished between polls still fires the toast. The first snapshot
  after mount never toasts (the briefing card owns "you arrived after a
  harvest").

## Frontend surfaces

| Surface | File | Behavior |
|---|---|---|
| Briefing card (Home) | `app/components/BriefingCard.tsx` + `app/lib/briefing.ts` | Leads with "12 pages changed since your last compile — 8 by Sarah Chen — not on your map yet" (`computePendingLine`; the attribution clause needs one person with ≥2 changes). Compile now / See all changes actions. Pending section ignores the compile-briefing dismissal (only compiling clears it) and is suppressed before the first-ever compile (BrainEmptyState owns that moment). |
| Changes drawer | `app/components/RecentChangesPanel.tsx` | Right-side drawer, grouped by day → author. Rows: new/updated/deleted pill, source badge, space, relative time, link to the source page; deleted docs struck-through, unlinked. Footer compile button disabled while a harvest/compile runs. Exports `ChangePill` / `changeAttribution` reused by `CompletionSummary`. |
| TopBar pill | `app/components/PendingChangesPill.tsx` | "N changed" (warning tone), hidden at zero; opens the drawer. |
| Cache invalidation | `app/components/TopBar.tsx` | Harvest running→complete invalidates `["changes"]` and fires the toast; compile running→complete invalidates `["changes"]` alongside the existing brain-data busting — the boundary moved, so the pill recounts to zero. |
| Data hook | `app/api/changes.ts` (+ `qk.changes()` in `keys.ts`) | `useChanges(since)` — single query shared by all surfaces. |

## Map overlay ("show me what changed on the island")

`brainMap/store.ts` `overlayMode` is now `'semantic' | 'attention' | 'recent'`.
The `'recent'` branch in `decodeHexes` (`brainMap/scene/HexField.tsx`) tints
tag hexes toward warm gold (`#F0B429`) proportional to `data.tagRecency`
(0..1 exponential decay, 90-day half-life, baked per-tag at compile time),
and desaturates stale ground so fresh spires carry the scene. The gold is
deliberately outside the attention risk palette (teal→amber→orange→red).

Why the *baked* recency and not a client-side recompute from note
timestamps: the map's content only changes at compile time, so the baked
signal is exactly as fresh as the map itself; recomputing would only shift
the decay by wall-clock time between compiles. Revisit if a user-selectable
recency window is wanted.

The Map / Attention / Recent segmented control in
`brainMap/chrome/BottomBar.tsx` (`OverlayToggle`) is the **first** UI wired
to `setOverlayMode` — it also unlocks the previously unreachable attention
overlay.

## Edge cases & invariants

- **Never compiled** → boundary is `null`, every log entry counts (capped by
  `limit`). The briefing card suppresses its pending section in this state.
- **Missing/empty/malformed log** → zeros; `read_log` skips bad lines.
- **Log rotation** (BACKLOG item 16, not yet implemented): if the boundary
  predates the oldest surviving log line, the response sets
  `truncated: true` and the drawer captions "showing the available history".
- **Notion timestamps**: filtering/grouping uses the log's `ts` (harvest
  time, local clock, trustworthy); `source_modified` is display-only.
- **Deleted docs** may have no manifest row (purged) — they keep their log
  fields and null out author/url.
- **`unchanged` skips** never appear in the feed (only `harvested` /
  `deleted_at_source` actions).

## Tests

`backend/tests/test_routes_changes.py` — endpoint empty/parse/dedupe/join,
`since` filtering + truncation flag, last-compile boundary from terrain.db,
settings default, and the `_maybe_auto_compile` on/off behavior.
Frontend: `briefing.ts` logic is covered by the existing vitest setup.
