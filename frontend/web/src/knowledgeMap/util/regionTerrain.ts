// "Where does this region actually live on the terrain?"
//
// The region tree and the hex field disagree: a bake can carry regions whose
// whole subtree owns ZERO hexes (in the current bake, 47 of 106 — 9 of them
// top-level). Such a region still has a `centroid` and a `radius`, but those
// describe a footprint the layout never materialised, so anything that trusts
// them points at terrain the region does not own. Two features got this wrong:
//
//   • HexField's focus dim tested subtree membership against the focused
//     region. An empty subtree matches no instance, so EVERY hex took the grey
//     branch — clicking a chat citation greyed the entire map.
//   • CameraAnimator fell back to `region.centroid` and flew to empty ground
//     (or, for a region with centroid {0,0}, to the world origin).
//
// Both now share one answer: resolve a region to the nearest ancestor that
// really does own hexes, and aim at that subtree's tallest hex. The resolve can
// legitimately come back `null` (a top-level region with no hexes anywhere) —
// callers must treat that as "this region has no terrain", not as index 0.

import type { RenderData, RegionEntry } from '../types';
import { hexToWorld } from './hexGeometry';

const HEX_FIELDS_PER_HEX = 5;

export type RegionPeak = { x: number; y: number; z: number };

export type RegionTerrain = {
  /** Ancestor chain INCLUDING self, nearest-first (self → parent → … → root),
   *  one entry per region. Cycle-safe: a malformed bake stops at the revisit
   *  instead of looping forever. */
  ancestorsOf: number[][];
  /** Does this region's subtree own at least one hex? */
  hasTerrain: (idx: number) => boolean;
  /** Tallest hex anywhere in this region's subtree, in RAW world coords
   *  (y un-scaled, exactly like `buildTopLevelRegions`). Null when the subtree
   *  owns no hexes. */
  peakOf: (idx: number) => RegionPeak | null;
  /** `idx` itself when its subtree owns hexes; otherwise the nearest ancestor
   *  whose subtree does; otherwise null. Null/out-of-range in → null out, so a
   *  stale citation against a re-baked map can't throw. */
  resolveTerrainRegionIdx: (idx: number | null) => number | null;
  /** Hexes in this region's subtree — its footprint. 0 for phantom regions. */
  hexCountOf: (idx: number) => number;
  /** Immediate children of `idx`, in `data.regions` order. */
  childrenOf: (idx: number) => number[];
};

/** Ancestor chain (incl. self) for every region, nearest-first. Shared by the
 *  focus-dim membership test and the terrain resolve so the two can never
 *  disagree about who owns whom. */
export function buildAncestorChains(regions: RegionEntry[]): number[][] {
  return regions.map((_, i) => {
    const chain: number[] = [];
    const seen = new Set<number>();
    let cur = i;
    // A parent cycle in a malformed bake must terminate, not hang.
    while (cur >= 0 && cur < regions.length && !seen.has(cur)) {
      seen.add(cur);
      chain.push(cur);
      cur = regions[cur].parentIdx;
    }
    return chain;
  });
}

/** Single pass over `data.hexes`, attributing each hex to every region on its
 *  ancestor chain — so a parent "owns" its descendants' hexes. Depth is ~3, so
 *  this stays O(hexes) in practice. Memoize on `data`. */
export function buildRegionTerrain(data: RenderData): RegionTerrain {
  const { regions, hexes, hexSize } = data;
  const ancestorsOf = buildAncestorChains(regions);

  // Explicit ownership flag rather than `peakHeight > 0`: a subtree whose hexes
  // are all height 0 still OWNS terrain, and conflating the two is what makes
  // phantom regions look real (and vice versa).
  const owns = new Array<boolean>(regions.length).fill(false);
  const hexCount = new Int32Array(regions.length);
  const peakY = new Float64Array(regions.length);
  const peakX = new Float64Array(regions.length);
  const peakZ = new Float64Array(regions.length);

  for (let i = 0; i < hexes.length; i += HEX_FIELDS_PER_HEX) {
    const regionIdx = hexes[i + 2];
    if (regionIdx < 0 || regionIdx >= regions.length) continue;
    const h = hexes[i + 3];
    let world: [number, number] | null = null;   // computed lazily, once per hex
    for (const a of ancestorsOf[regionIdx]) {
      hexCount[a] += 1;
      if (!owns[a] || h > peakY[a]) {
        if (world === null) world = hexToWorld(hexes[i], hexes[i + 1], hexSize);
        owns[a] = true;
        peakY[a] = h;
        peakX[a] = world[0];
        peakZ[a] = world[1];
      }
    }
  }

  const children: number[][] = regions.map(() => []);
  regions.forEach((r, i) => {
    if (r.parentIdx >= 0 && r.parentIdx < regions.length) children[r.parentIdx].push(i);
  });

  const inRange = (idx: number) => Number.isInteger(idx) && idx >= 0 && idx < regions.length;

  const hasTerrain = (idx: number) => inRange(idx) && owns[idx];

  const peakOf = (idx: number): RegionPeak | null =>
    hasTerrain(idx) ? { x: peakX[idx], y: peakY[idx], z: peakZ[idx] } : null;

  const resolveTerrainRegionIdx = (idx: number | null): number | null => {
    if (idx === null || !inRange(idx)) return null;
    for (const a of ancestorsOf[idx]) {
      if (owns[a]) return a;
    }
    return null;
  };

  const hexCountOf = (idx: number) => (inRange(idx) ? hexCount[idx] : 0);
  const childrenOf = (idx: number) => (inRange(idx) ? children[idx] : []);

  return { ancestorsOf, hasTerrain, peakOf, resolveTerrainRegionIdx, hexCountOf, childrenOf };
}

// One RegionTerrain per bake. Several components (HexField, RegionLabels, the
// hover resolver, the sidebar) all need the same answer for the same `data`;
// a WeakMap keyed on the data object means the O(hexes) pass runs once and the
// entry is collected with the bake.
const cache = new WeakMap<RenderData, RegionTerrain>();
export function regionTerrainFor(data: RenderData): RegionTerrain {
  let t = cache.get(data);
  if (!t) {
    t = buildRegionTerrain(data);
    cache.set(data, t);
  }
  return t;
}
