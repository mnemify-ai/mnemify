# Frontend Improvements — audit & menu

A working menu of what's still to do on the Mnemify dashboard (`frontend/web/`,
React 18 + Vite 5 + TS, Tailwind + CSS-var theme). Distinct from:

- [`ROADMAP.md`](ROADMAP.md) — the product/UX roadmap (jobs-to-be-done, phasing).
- [`BACKLOG.md`](BACKLOG.md) — the engineering backlog (small follow-ups, mostly backend).

This doc is the **frontend-focused** view: features, polish, a11y, and UX fixes
specific to the dashboard. Each item names files where the change lands, says
*why*, and tags rough effort.

Last refreshed: 2026-05-15 after a top-to-bottom audit. The plan that fed this
refresh lives at `~/.claude/plans/you-are-an-expert-unified-pony.md`.

---

## Currently open (the live menu)

These are the eight tiers in flight. Each ships as its own PR.

| Tier | What | Files | Effort |
|---|---|---|---|
| T7 | **Doc cleanup** — this refresh | `docs/frontend_improvements.md` | ~30m |
| T1 | **Design-token foundation** — `--surface-0/1/2/overlay`, `--opacity-disabled/hover/pressed`, `.tabular-nums` utility | `src/app/theme/index.css`, `tailwind.config.ts`, migrate `FloatingSourcesPanel`, brainMap `Sidebar`/`BottomBar`, `TagProvenanceDrawer`, `Button` | ~0.5d |
| T2 | **BrainMap hex hover tooltip** — close the deferred TODO at `HexField.tsx:121-128` | `src/brainMap/scene/HexField.tsx`, new `src/brainMap/chrome/HexTooltip.tsx` | ~1d |
| T3 | **Documents region + tag filters** — replace the "coming soon" stub at `DocFiltersPanel.tsx:106-108` | `src/app/components/DocFiltersPanel.tsx`, `src/app/lib/useDocFilters.ts`, `src/app/pages/DocumentsPage.tsx` | ~1d |
| T4 | **`DocViewerPane` decomposition + state primitives** — split 978-line file into shell + Header/Body/Sidebar/States; swap `animate-pulse` → `Skeleton`, plain text 404 → `EmptyState`, errors → `ErrorState` | `src/app/components/DocViewerPane.tsx` → barrel + 4 siblings | ~1d |
| T5 | **Compile Report polish** — responsive stage grid (8/4/2/1), status left-rule, swap inline log → `LiveLogTail`, optional sparkline if a history endpoint exists | `src/app/pages/CompileReportPage.tsx` | ~0.5d |
| T6 | **Wizard validation** — on-blur auto-Test (debounced 400ms), inline field errors beneath inputs, guardrail preserved | `src/app/components/wizards/{Notion,Confluence,Obsidian}Wizard.tsx` | ~0.5d |
| T8 | **Humanizer + micro-moments** — run `humanizer` skill across toasts / empty states / error states; add reset toast; verify `SynapseBurst` reduced-motion gate | toast strings + state-primitive bodies | ~0.5d |

Total: ~5 days. Each tier is independently mergeable. See the verification
checklist near the bottom of this file (still current).

---

## What's shipped that earlier drafts of this doc thought was still open

Auditing the actual codebase as of 2026-05-15 found that several P0/P1 items
from earlier drafts were already in the tree. Listed here so future planners
don't burn cycles re-proposing them:

**UI primitives** (all present in `src/app/components/ui/`):
- `Skeleton.tsx` (line / block / circle variants, honors `prefers-reduced-motion`)
- `EmptyState.tsx` (icon + title + description + action)
- `ErrorState.tsx` (same shape + retry callback)
- `Tooltip.tsx` (Radix-powered, `aria-describedby` wired)
- `Kbd.tsx` (`<kbd>` styled with bone surface + mono font)
- `Segmented.tsx` (Radix RadioGroup wrapper)
- `Button.tsx` with `destructive` variant + `loading` prop + `aria-busy`

**Theme tokens** (`src/app/theme/index.css`):
- Semantic intent colors (`--color-success/warning/info/danger`)
- Motion durations (`--dur-fast: 150ms`, `--dur-base: 240ms`, `--dur-slow: 320ms`, `--dur-exit: 180ms`)
- Custom focus-visible ring (2px offset magenta @ 0.85)
- Newsreader font (Google Fonts import) replaces Times
- Dark-mode overrides for every brand variable

**Features:**
- `CommandPalette.tsx` (⌘K, ~413 LoC) — A1 done.
- `OnboardingChecklist.tsx` (4 steps, `localStorage.mnemify.onboarded`) — A2 done.
- `BrainMap` V2 redesign — `BottomBar.tsx` grid row replaces the old floating overlays. `ArcsToggle` is now inlined in `BottomBar` (lines 36–62). **`Legend.tsx` no longer exists** — earlier F1/F2 references are stale.
- `ActivityFeed.tsx` is gone — F3 reference is stale.
- `HarvestStatusPage` keyboard shortcuts (S/C/R/?) wired via the SSE state machine.
- `LiveLogTail` virtualized (TanStack Virtual) with jump-to-latest, scroll shadows, `aria-live="polite"`.
- `HarvestProgressBar` has full `aria-label` with counts + rate + ETA.
- DocumentsPage virtualization, `aria-sort` on headers, two distinct empty states, mobile filter drawer, URL-serialized filters.

Track E (the `ui-ux-pro-max` glow-up) is **partially landed**: the design
direction (Editorial Minimalism × Nature Distilled) is committed; tokens are
~80% in. The remaining 20% is T1 above (surface elevation, state opacity,
tabular-nums).

---

## Stale references — do not act on these

These items in earlier drafts of this doc reference components that no longer
exist or describe state that no longer holds. Kept as a tombstone so reviewers
know not to revive them:

- **F1 — Remove `ArcsToggle.tsx`**: the file never existed as a separate component; `ArcsToggle` is inlined in `BottomBar.tsx`.
- **F2 — Legend panel scroll + clickable + hierarchy**: no `Legend.tsx` in `src/brainMap/chrome/` (current contents: `BottomBar`, `Breadcrumb`, `Header`, `Sidebar`, `StatsPanel`, `TimeScrubber`). The legend was descoped during the V2 redesign.
- **F3 — Remove `ActivityFeed`**: `HomePage.tsx` no longer imports `ActivityFeed`; the component file is gone.
- **A1 / A2 / E4 primitives**: shipped; see the section above.
- **C0 motion tokens + focus ring**: shipped; the gap was elevation + state opacity, both in T1.

---

## Track A — Roadmap product features (the unfinished half)

Lifted from `ROADMAP.md`. Items already shipped are marked ✓.

| # | Item | Job | Impact | Effort | Priority |
|---|---|---|---|---|---|
| A1 ✓ | ⌘K command palette | 2, 3 | High | shipped | — |
| A2 ✓ | Onboarding checklist | 1 | Med | shipped | — |
| A3 | Daily Briefing card on Home (heuristic insights) | 2 | Very high | Med | P1 |
| A4 | Export `.mnemify` as zip (Settings → Data; needs `GET /api/export`) | 4 | Med | Low | P1 |
| A5 | Reset everything (double-confirm, backup to `.mnemify-backup/`) | 4 | Med | Low | P1 |
| A6 | Audit log viewer (`/settings/audit` reading `.mnemify/audit-log.jsonl`) | 4 | Med | Low + backend endpoint | P2 |
| A7 | Scheduled harvests (cron config in Settings + backend daemon) | 1 | Med | Low–Med | P2 |
| A8 | OAuth flows for Notion + Atlassian (replace token paste) | 1 | High | Med–High | P3 (v4) |
| A9 | Ask / chat surface (`/ask`, BYOK Claude/OpenAI) | 3 | Very high | High (needs Reasoner) | P3 (v4) |
| A10 | Entity pages (people / projects) | 2, 3 | High | Med–High | P3 (v4) |
| A11 | Context-export bundles (markdown bundle of every note about X) | 3 | High | Med | P3 (v4) |

> ⚠ A5 (Reset) smoke-tests must run against a throwaway `.mnemify-test/` dir
> only — the live reset endpoint wipes the real `.mnemify/`.

---

## Track A.1 — Smaller v2.1 wins

| # | Item | File hint | Status |
|---|---|---|---|
| A12 | Drag-folder-to-input in Obsidian wizard | `wizards/ObsidianWizard.tsx` | Open |
| A13 | Detect doubled-up tilde (`~/Users/<name>/…`) and auto-fix | Wizard path inputs | Open |
| A14 | Sticky filter chips on Documents | `FilterChips.tsx` already exists; verify integration | Likely shipped — verify |
| A15 | Empty-source CTA on Home when no sources connected | `pages/HomePage.tsx`, `FloatingSourcesPanel.tsx` | Open |

---

## Track B — Engineering follow-ups (still applicable)

The original §B referenced `frontend/src/**/*.jsx` from the old prototype. The
ideas still apply to today's `frontend/web/src/**/*.tsx`:

| # | Item | Path | Status |
|---|---|---|---|
| B1 | `aria-label` + `role="status"` on per-source progress cards | `HarvestProgressBar.tsx` | ✓ shipped (lines 43-55) |
| B2 | Tooltip on the `~` ETA prefix | `pages/HarvestStatusPage.tsx`, ETA renderer | Open |
| B3 | Keyboard shortcuts for harvest controls | `pages/harvest/HarvestStatusPage.tsx` | ✓ shipped (lines 112-160; S/C/R/?) |
| B4 | Lift magic numbers to named constants | `app/sse/`, `app/lib/` | Open |
| B5 | Vitest coverage for utils | `app/lib/__tests__/` | Partial — extend with T3 + T6 new utils |

---

## Track C — Glow-up polish (partially landed)

Below: only the items that haven't shipped. The Skeleton / EmptyState /
ErrorState / Tooltip / Kbd / Segmented / Motion-tokens / Focus-ring items
proposed under C0 all shipped.

- **Surface elevation tokens** — T1 covers this.
- **State opacity tokens** — T1 covers this.
- **Tabular numerics** — T1 covers this.
- **Responsive audit** — verify Documents table, ManageScopeDialog, DocFiltersPanel at `xs`/`sm`/`md` breakpoints; the audit found mostly-good responsive behavior but `DocViewerPane` (978 lines) likely has hardcoded widths buried inside; T4 split is the natural moment to fix.
- **Compile stage card responsiveness** — T5 covers this.
- **Compile stage left-rule** — T5 covers this.
- **DocDrawerBody skeleton + 404 state** — folded into T4.
- **Log tail scroll-shadow + auto-scroll-paused** — already shipped in `LiveLogTail.tsx`. Verify nothing regressed during T5's swap.

---

## Track D — Anthropomorphic micro-moments

Consolidated into T8.

- **First connection toast**: "First synapse formed." — verify wired in NotionWizard / ConfluenceWizard / ObsidianWizard.
- **Harvest complete toast**: "Your brain learned N new memories." — `CompletionSummary.tsx` headline. Verify N is real.
- **Reset toast**: "Memory wiped. Ready when you are." — add (none today).
- **`SynapseBurst`** — exists; verify it's gated by `prefers-reduced-motion`.
- **Optional chime on harvest complete** — Settings → General toggle, off by default. Defer; only ship if there's user demand.

---

## Track E — UI/UX glow-up (`ui-ux-pro-max`) — the open 20%

The full Track E direction (Editorial Minimalism × Nature Distilled palette,
motion tokens, focus ring, primitives) is already adopted. What's still open
maps cleanly to the live tiers above:

- E1 (semantic / surface / focus / motion / type-scale tokens) → **T1**.
- E3.1 (hex spire hover tooltip) → **T2**.
- E3.2 (Compile stage card density + crossfade + trend emphasis) → **T5**.
- E3.3 (Documents data-table polish: `aria-sort` shipped, direct labels shipped, region/tag filters open) → **T3**.
- E3.4 (Settings nav hierarchy + form field rhythm + inline validation + destructive emphasis) → **T6** covers wizards; the rest is small and folds into T1 token migration.
- E5 (motion language consistency) → emerges from T1 tokens; no separate work.
- E6 (a11y — focus order, color-not-only, form labels, aria-live, contrast audit) → ad hoc inside each tier's PR.
- E7 (responsive matrix) → applied per page during T4/T5; no separate sweep.

If a specific surface lands ambiguously during implementation, invoking the
`ui-ux-pro-max` skill on that surface is cheap (one tool call).

---

## Verification checklist (use for every tier PR)

1. **Typecheck**: `cd frontend/web && npx tsc -b` — clean.
2. **Vitest**: `npm test` — green. Add tests alongside any new utility.
3. **Dev walk**: `./run.sh --dev`. Walk every route at desktop (≥1280px), tablet (768px), mobile (375px).
4. **Dark mode** toggle (`html.dark`): no hard-coded hex strings on new surfaces.
5. **Reduced motion**: enable OS-level "Reduce motion"; confirm new transitions honor it.
6. **A11y spot check**: keyboard-only walk of touched controls; axe DevTools on each route.
7. **Reset path** (A5 only): smoke-test against a throwaway `.mnemify-test/` dir — never the real `.mnemify/`.
8. **Copy pass**: run `humanizer` over new toast + empty/error strings (T8).
9. **Final pass**: run `/review` on the diff.

---

## Decision principles

1. Every feature must serve one of the four jobs in `ROADMAP.md` (Connect / Know / Use / Trust).
2. Quick wins ship first — they compound by making every other feature easier to use.
3. Real-data swap was gating for v4 bets (A9–A11); it has shipped, so those are unblocked when prioritized.
4. Anthropomorphic copy is free; slip it in everywhere.
