// Resolves the Ask agent's live "I'm looking here" region ids into the
// top-level region slots the map actually draws medallions for.
//
// The backend pulses whatever region a touched node belongs to, and that can
// be a *leaf* sub-region — but RegionLabels only renders `level === 0`
// regions (see buildTopLevelRegions). Without walking up `parentIdx` to the
// top-level ancestor, a pulse on a nested region silently matches nothing.

import { useEffect, useMemo, useState } from 'react';
import { nextExpiry, useMapPulseStore } from '../../app/lib/mapPulseStore';
import type { RenderData } from '../types';

/** Top-level region indices (into `data.regions`) for a set of region node
 *  ids. Ids that don't name a region — or name one that isn't in this bake —
 *  are dropped. Pure; the walk to the top-level ancestor is the whole point. */
export function resolvePulseRegionIdxs(
  data: RenderData,
  ids: Iterable<string>,
): Set<number> {
  const out = new Set<number>();
  const idxById = new Map<string, number>();
  for (let i = 0; i < data.regions.length; i++) {
    idxById.set(data.regions[i].id, i);
  }
  for (const id of ids) {
    const idx = idxById.get(id);
    if (idx === undefined) continue;
    let cur = idx;
    // Guard the walk: a malformed bake with a parent cycle must not hang.
    for (let hops = 0; hops < data.regions.length; hops++) {
      const parent = data.regions[cur].parentIdx;
      if (parent < 0 || parent >= data.regions.length) break;
      cur = parent;
    }
    out.add(cur);
  }
  return out;
}

/**
 * Live set of top-level region indices to pulse. Self-expiring: each entry
 * carries a deadline, and this schedules a prune at the soonest one so the
 * ring actually stops rather than lingering until the next step arrives.
 */
export function useAgentPulseRegions(data: RenderData): Set<number> {
  const pulses = useMapPulseStore((s) => s.pulses);
  const prune = useMapPulseStore((s) => s.prune);

  // Re-run the prune scheduler when the soonest deadline moves, not on every
  // pulse-map identity change.
  const soonest = nextExpiry(pulses);
  const [, forceTick] = useState(0);
  useEffect(() => {
    if (soonest === null) return;
    const delay = Math.max(0, soonest - Date.now());
    const t = setTimeout(() => {
      prune();
      forceTick((n) => n + 1);
    }, delay + 16);
    return () => clearTimeout(t);
  }, [soonest, prune]);

  return useMemo(
    () => resolvePulseRegionIdxs(data, Object.keys(pulses)),
    [data, pulses],
  );
}
