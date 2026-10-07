// Timeline scrubber data: when each spire and each region first appeared, and
// when it was last touched, derived from the note registry's created/updated
// stamps (mocknotes.json). The bake has no dates of its own — `tagRecency` is
// a score relative to bake time, useless for "rewind to March" — so the index
// is built client-side once the notes load and resolved per hex in HexField.
//
// Everything here is pure; `useTimelineSync` (below) is the only hook.

import { useEffect, useMemo } from 'react';
import { useMapTimelineStore } from '../../app/lib/mapTimelineStore';
import { useNotes } from '../data/useNotes';
import { useKnowledgeMapStore } from '../store';
import type { Note, RenderData } from '../types';

export const DAY_MS = 86_400_000;
/** "Changed recently" window behind the cutoff for the changes overlay. */
export const CHANGES_WINDOW_MS = 30 * DAY_MS;

export type TimelineIndex = {
  /** tagIdx → epoch ms of the earliest note carrying the tag; NaN = unknown. */
  tagFirstSeen: Float64Array;
  /** tagIdx → epoch ms of the latest update to any note carrying the tag. */
  tagLastTouched: Float64Array;
  /** regionIdx (any level) → earliest note in its subtree; NaN = unknown. */
  regionFirstSeen: Float64Array;
  /** regionIdx (any level) → latest update in its subtree; NaN = unknown. */
  regionLastTouched: Float64Array;
  /** Every note's created stamp, sorted ascending — for "N notes by <date>". */
  noteCreated: Float64Array;
  /** Span of the scrubber. Equal when only one dated note exists. */
  minMs: number;
  maxMs: number;
};

/** Settings the scrubber UI owns. `cutoff` is epoch ms; hexes whose first
 *  note is later than it are "not yet born". */
export type TimelineState = {
  cutoff: number;
  /** Paint what changed in the CHANGES_WINDOW before the cutoff. */
  showChanges: boolean;
};

function parseStamp(s: string | undefined | null): number {
  if (!s) return NaN;
  const ms = Date.parse(s);
  return Number.isFinite(ms) ? ms : NaN;
}

function minNaN(a: number, b: number): number {
  if (Number.isNaN(a)) return b;
  if (Number.isNaN(b)) return a;
  return a < b ? a : b;
}
function maxNaN(a: number, b: number): number {
  if (Number.isNaN(a)) return b;
  if (Number.isNaN(b)) return a;
  return a > b ? a : b;
}

/** Build the index. Returns null when no note carries a parseable date, so
 *  the UI can say "no dates in this map" instead of showing a dead slider. */
export function buildTimelineIndex(data: RenderData, notes: Note[]): TimelineIndex | null {
  const tagCount = data.tagIndex.length;
  const regionCount = data.regions.length;
  const tagIdxById = new Map<string, number>();
  for (let i = 0; i < tagCount; i++) tagIdxById.set(data.tagIndex[i], i);
  const regionIdxById = new Map<string, number>();
  for (let i = 0; i < regionCount; i++) regionIdxById.set(data.regions[i].id, i);

  const tagFirstSeen = new Float64Array(tagCount).fill(NaN);
  const tagLastTouched = new Float64Array(tagCount).fill(NaN);
  const regionFirstSeen = new Float64Array(regionCount).fill(NaN);
  const regionLastTouched = new Float64Array(regionCount).fill(NaN);
  const created: number[] = [];
  let minMs = NaN;
  let maxMs = NaN;

  for (const n of notes) {
    const c = parseStamp(n.createdAt);
    const u = maxNaN(parseStamp(n.updatedAt), c);
    if (Number.isNaN(c) && Number.isNaN(u)) continue;
    const first = minNaN(c, u);
    created.push(first);
    minMs = minNaN(minMs, first);
    maxMs = maxNaN(maxMs, u);

    const tags = new Set<string>(n.tagIds);
    if (n.primaryTagId) tags.add(n.primaryTagId);
    for (const t of tags) {
      const ti = tagIdxById.get(t);
      if (ti === undefined) continue;
      tagFirstSeen[ti] = minNaN(tagFirstSeen[ti], first);
      tagLastTouched[ti] = maxNaN(tagLastTouched[ti], u);
    }
    const ri = regionIdxById.get(n.regionId);
    if (ri !== undefined) {
      regionFirstSeen[ri] = minNaN(regionFirstSeen[ri], first);
      regionLastTouched[ri] = maxNaN(regionLastTouched[ri], u);
    }
  }
  if (created.length === 0) return null;

  // Roll leaf dates up the region tree so a parent is "born" with its first
  // child and "touched" with its latest. Walk every region to its root; the
  // tree is tiny, so the repeated climbs cost nothing.
  for (let i = 0; i < regionCount; i++) {
    const f = regionFirstSeen[i];
    const l = regionLastTouched[i];
    if (Number.isNaN(f) && Number.isNaN(l)) continue;
    let cur = data.regions[i].parentIdx;
    for (let hops = 0; hops < regionCount && cur >= 0 && cur < regionCount; hops++) {
      regionFirstSeen[cur] = minNaN(regionFirstSeen[cur], f);
      regionLastTouched[cur] = maxNaN(regionLastTouched[cur], l);
      cur = data.regions[cur].parentIdx;
    }
  }

  created.sort((a, b) => a - b);
  return {
    tagFirstSeen,
    tagLastTouched,
    regionFirstSeen,
    regionLastTouched,
    noteCreated: Float64Array.from(created),
    minMs,
    maxMs,
  };
}

/** Has this hex appeared by `cutoff`? Tag hexes answer from their tag, plain
 *  terrain from its region; anything undated stays visible so a map with
 *  partial dates never loses terrain it cannot place in time. */
export function isBornBy(
  idx: TimelineIndex,
  tagIdx: number,
  regionIdx: number,
  cutoff: number,
): boolean {
  if (tagIdx >= 0) {
    const t = idx.tagFirstSeen[tagIdx];
    if (!Number.isNaN(t)) return t <= cutoff;
  }
  const r = idx.regionFirstSeen[regionIdx];
  return Number.isNaN(r) || r <= cutoff;
}

/** Was this hex's tag (or, for plain terrain, its region) updated inside the
 *  changes window ending at `cutoff`? */
export function changedBy(
  idx: TimelineIndex,
  tagIdx: number,
  regionIdx: number,
  cutoff: number,
  windowMs = CHANGES_WINDOW_MS,
): boolean {
  const last = tagIdx >= 0 ? idx.tagLastTouched[tagIdx] : idx.regionLastTouched[regionIdx];
  if (Number.isNaN(last)) return false;
  return last <= cutoff && last > cutoff - windowMs;
}

/** Notes created on or before `cutoff` (binary search over the sorted stamps). */
export function notesBy(idx: TimelineIndex, cutoff: number): number {
  const a = idx.noteCreated;
  let lo = 0;
  let hi = a.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (a[mid] <= cutoff) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Notes created inside the changes window ending at `cutoff`. */
export function notesChangedBy(idx: TimelineIndex, cutoff: number, windowMs = CHANGES_WINDOW_MS): number {
  return notesBy(idx, cutoff) - notesBy(idx, cutoff - windowMs);
}

/** Round a span to whole days for the slider. */
export function sliderDomain(idx: TimelineIndex): { minDay: number; maxDay: number } {
  const minDay = Math.floor(idx.minMs / DAY_MS);
  const maxDay = Math.max(minDay, Math.ceil(idx.maxMs / DAY_MS));
  return { minDay, maxDay };
}

export function formatCutoff(ms: number, locale?: string): string {
  return new Date(ms).toLocaleDateString(locale, { year: 'numeric', month: 'short', day: 'numeric' });
}

/** Load the notes while the scrubber is open, build the index against this
 *  bake, and hand it to the map store. Mounted in KnowledgeMap's ReadyChrome. */
export function useTimelineSync(data: RenderData, notesUrl: string) {
  const open = useKnowledgeMapStore((s) => s.timelineOpen);
  const setTimelineIndex = useKnowledgeMapStore((s) => s.setTimelineIndex);
  const notes = useNotes(notesUrl, open);
  const index = useMemo(
    () => (notes.status === 'ready' ? buildTimelineIndex(data, notes.notes) : null),
    [data, notes],
  );
  useEffect(() => {
    setTimelineIndex(index, notes.status === 'ready' || notes.status === 'error');
  }, [index, notes.status, setTimelineIndex]);

  // Publish the cutoff app-wide so the Ask dock can ask "as of" it. Only a
  // cutoff strictly before the latest note counts: parked at the end, the
  // map shows the present and a question should be asked normally.
  const cutoff = useKnowledgeMapStore((s) => s.timeline?.cutoff ?? null);
  const setAsOf = useMapTimelineStore((s) => s.setAsOf);
  useEffect(() => {
    const active = open && index !== null && cutoff !== null && cutoff < index.maxMs;
    setAsOf(active ? cutoff : null);
  }, [open, index, cutoff, setAsOf]);
  useEffect(() => () => setAsOf(null), [setAsOf]);
}
