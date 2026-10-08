// Pure helpers for the region workspace pages. No DOM, no React — unit-tested
// under the node-only vitest config like lib/actionItems.ts.

import type { ActionItem } from "../api/actionItems";
import type { MemoryGroup, MemoryItem } from "../api/regions";
import type { Note, RegionEntry } from "../data/types";

/** True when `candidateId` is `regionId` or lies somewhere beneath it. */
export function isInSubtree(
  regionPathById: Map<string, RegionEntry[]>,
  regionId: string,
  candidateId: string | null | undefined,
): boolean {
  if (!candidateId) return false;
  const path = regionPathById.get(candidateId);
  if (!path) return false;
  return path.some((r) => r.id === regionId);
}

/** Notes per source, most common first. */
export function sourcesBreakdown(notes: Note[]): { source: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const n of notes) counts.set(n.source, (counts.get(n.source) ?? 0) + 1);
  return [...counts.entries()]
    .map(([source, count]) => ({ source, count }))
    .sort((a, b) => b.count - a.count || a.source.localeCompare(b.source));
}

/** Latest `updatedAt` (falling back to `createdAt`) across the notes. */
export function lastTouchedAt(notes: Note[]): string | null {
  let best: string | null = null;
  for (const n of notes) {
    const stamp = n.updatedAt || n.createdAt;
    if (stamp && (best === null || stamp > best)) best = stamp;
  }
  return best;
}

/**
 * Items whose attributed region sits inside `regionId`'s subtree, minus the
 * ones the user dismissed. Used when the workspace falls back to the global
 * action-items list (before the server detail lands).
 */
export function filterActionItemsToRegion<T extends ActionItem>(
  items: T[],
  regionPathById: Map<string, RegionEntry[]>,
  regionId: string,
): T[] {
  return items.filter(
    (it) => it.user_status !== "dismissed" && isInSubtree(regionPathById, regionId, it.region_id),
  );
}

/** Drop `[cN]` citation markers (and the spaces they leave behind) so a saved
 *  memory body reads as prose, not as an answer transcript. */
export function stripCitationMarkers(text: string): string {
  return text
    .replace(/\s*\[c\d+\](?:\s*\[c\d+\])*/g, "")
    .replace(/[ \t]+([.,;:!?])/g, "$1")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

const TITLE_MAX = 64;

/** A memory title from the question that produced the answer — the same
 *  64-char truncation the thread switcher uses for thread titles. */
export function memoryTitleFromQuestion(question: string | null | undefined): string {
  const q = (question ?? "").replace(/\s+/g, " ").trim();
  if (!q) return "Saved finding";
  return q.length > TITLE_MAX ? `${q.slice(0, TITLE_MAX - 1)}…` : q;
}

/**
 * Flatten the server's per-region groups into the Memory tab's sections:
 * "This region" first (always present, even when empty), then one section per
 * direct child in path order with everything beneath it rolled up.
 */
export function groupMemoryBySubregion(
  groups: MemoryGroup[],
  regionId: string,
  childrenByRegionId: Map<string, RegionEntry[]>,
  regionPathById: Map<string, RegionEntry[]>,
): { id: string; title: string; isSelf: boolean; items: MemoryItem[] }[] {
  const self = groups.find((g) => g.is_self || g.region_id === regionId);
  const out: { id: string; title: string; isSelf: boolean; items: MemoryItem[] }[] = [
    { id: regionId, title: "This region", isSelf: true, items: self?.items ?? [] },
  ];
  const children = childrenByRegionId.get(regionId) ?? [];
  const byChild = new Map<string, MemoryItem[]>();
  const stray: MemoryItem[] = [];
  for (const g of groups) {
    if (g.is_self || g.region_id === regionId) continue;
    const path = regionPathById.get(g.region_id);
    const selfIdx = path ? path.findIndex((r) => r.id === regionId) : -1;
    const child = path && selfIdx >= 0 ? path[selfIdx + 1] : undefined;
    if (child) {
      const list = byChild.get(child.id) ?? [];
      list.push(...g.items);
      byChild.set(child.id, list);
    } else {
      stray.push(...g.items);
    }
  }
  for (const c of children) {
    const items = byChild.get(c.id);
    if (items && items.length) out.push({ id: c.id, title: c.name, isSelf: false, items });
  }
  // Groups the client-side tree doesn't know (a stale bake) still show up.
  for (const [cid, items] of byChild) {
    if (!children.some((c) => c.id === cid)) {
      const name = groups.find((g) => g.region_id === cid)?.region_name ?? cid;
      out.push({ id: cid, title: name, isSelf: false, items });
    }
  }
  if (stray.length) out.push({ id: "__other__", title: "Other sub-regions", isSelf: false, items: stray });
  return out;
}
