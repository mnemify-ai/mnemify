// Pure surfacing/derivation logic for the Home "Since you were last here"
// briefing card. Kept separate from the JSX so the show/hide rules and the
// delta/attention shaping can be unit-tested without a DOM (the test env is
// node-only — see vitest.config.ts).

import type { BurningItem, TerrainReport } from "../api/terrain";
import type { ChangeEntry, ChangesSummary } from "../api/changes";
import { relativeTime } from "./relativeTime";

/** How old the last harvest may get before we nudge "check your sources". */
export const STALE_HARVEST_MS = 24 * 60 * 60 * 1000;
/** Window in which the pending line uses "Harvested Nh ago" framing. */
export const RECENT_HARVEST_MS = 12 * 60 * 60 * 1000;
/** How long a dismissed harvest nudge stays hidden. */
export const HARVEST_NUDGE_SNOOZE_MS = 24 * 60 * 60 * 1000;

export interface BriefingView {
  /** ISO timestamp of the compile this briefing describes (= generated_at). */
  compiledAt: string;
  /** Human chips like "+12 notes", "+3 tags", "-1 connections" (nonzero only). */
  deltaChips: string[];
  /** Top attention items worth surfacing (level ≥ medium, capped). */
  burning: BurningItem[];
}

export interface BriefingArgs {
  report: TerrainReport | null | undefined;
  /** Has the user clicked a spire at least once (past first-interaction)? */
  hasClickedTag: boolean;
  /** generated_at the user last dismissed, or null if never. */
  ackedAt: string | null;
}

const MAX_BURNING = 4;

function signed(n: number): string {
  return n > 0 ? `+${n}` : `${n}`;
}

/**
 * Decide whether to show the briefing and, if so, what it says. Returns null
 * when the card should not render. Rules:
 *   • need a compiled map with a timestamp
 *   • only after first tag-click (so it never co-exists with the map hint)
 *   • not if this exact compile was already acknowledged
 *   • not if there's nothing to report (no deltas and nothing hot)
 */
export function computeBriefing({
  report,
  hasClickedTag,
  ackedAt,
}: BriefingArgs): BriefingView | null {
  if (!report?.exists || !report.generated_at) return null;
  if (!hasClickedTag) return null;
  if (ackedAt === report.generated_at) return null;

  const deltas = report.stats?.deltas ?? null;
  const deltaChips: string[] = [];
  if (deltas) {
    if (deltas.notes) deltaChips.push(`${signed(deltas.notes)} notes`);
    if (deltas.tags) deltaChips.push(`${signed(deltas.tags)} tags`);
    if (deltas.edges) deltaChips.push(`${signed(deltas.edges)} connections`);
  }

  const burning = (report.burning ?? [])
    .filter((b) => b.attentionLevel !== "none" && b.attentionLevel !== "low")
    .slice(0, MAX_BURNING);

  if (deltaChips.length === 0 && burning.length === 0) return null;

  return { compiledAt: report.generated_at, deltaChips, burning };
}

/**
 * Shape the pending-changes headline for the briefing card:
 * "12 pages changed since your last compile — 8 by Sarah Chen".
 * The attribution clause appears only when one person clearly leads
 * (≥ 2 changes), so a long tail of single edits doesn't call anyone out.
 *
 * When the last harvest is recent (opts.lastHarvestTime within
 * RECENT_HARVEST_MS) and a summary is supplied, the head switches to
 * harvest-anchored framing: "Harvested 3h ago · 4 new · 2 updated".
 */
export function computePendingLine(
  total: number,
  changes: ChangeEntry[],
  opts?: {
    summary?: ChangesSummary;
    lastHarvestTime?: string | null;
    now?: number;
  },
): string | null {
  if (total <= 0) return null;
  let head = `${total.toLocaleString()} page${total === 1 ? "" : "s"} changed since your last compile`;
  const harvestedAt = opts?.lastHarvestTime ? Date.parse(opts.lastHarvestTime) : NaN;
  if (
    opts?.summary &&
    !Number.isNaN(harvestedAt) &&
    (opts.now ?? Date.now()) - harvestedAt < RECENT_HARVEST_MS
  ) {
    const buckets = [
      opts.summary.new > 0 ? `${opts.summary.new} new` : null,
      opts.summary.updated > 0 ? `${opts.summary.updated} updated` : null,
      opts.summary.deleted > 0 ? `${opts.summary.deleted} deleted` : null,
    ].filter(Boolean);
    if (buckets.length > 0) {
      head = `Harvested ${relativeTime(opts.lastHarvestTime)} · ${buckets.join(" · ")}`;
    }
  }
  const counts = new Map<string, number>();
  for (const c of changes) {
    const who = c.last_modified_by || c.author;
    if (!who) continue;
    counts.set(who, (counts.get(who) ?? 0) + 1);
  }
  let topName: string | null = null;
  let topCount = 0;
  for (const [name, count] of counts) {
    if (count > topCount) {
      topName = name;
      topCount = count;
    }
  }
  if (topName && topCount >= 2) return `${head} — ${topCount} by ${topName}`;
  return head;
}

export interface HarvestNudge {
  /** ISO time of the last completed harvest, for "Last harvested 2d ago". */
  lastHarvestTime: string;
  /** Suggest setting up a morning schedule (no schedule enabled yet). */
  suggestSchedule: boolean;
}

/**
 * Decide whether to offer a harvest ("Last harvested 2d ago — check your
 * sources for new info?"). Returns null when:
 *   • never harvested (the empty states own that journey)
 *   • the last harvest is fresh (< STALE_HARVEST_MS)
 *   • a harvest is already running
 *   • uncompiled changes exist (the compile nudge takes priority — never
 *     stack two asks)
 *   • the user snoozed the nudge and the snooze hasn't expired
 */
export function computeHarvestNudge({
  lastHarvestTime,
  scheduleEnabled,
  harvestRunning,
  pendingTotal,
  snoozedUntil,
  now = Date.now(),
}: {
  lastHarvestTime: string | null | undefined;
  scheduleEnabled: boolean;
  harvestRunning: boolean;
  pendingTotal: number;
  snoozedUntil: number | null;
  now?: number;
}): HarvestNudge | null {
  if (!lastHarvestTime) return null;
  const harvestedAt = Date.parse(lastHarvestTime);
  if (Number.isNaN(harvestedAt)) return null;
  if (now - harvestedAt < STALE_HARVEST_MS) return null;
  if (harvestRunning) return null;
  if (pendingTotal > 0) return null;
  if (snoozedUntil !== null && now < snoozedUntil) return null;
  return { lastHarvestTime, suggestSchedule: !scheduleEnabled };
}
