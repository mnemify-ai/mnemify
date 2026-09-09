// Geometry the cartographer's-paper plane needs, derived in one pass over the
// hex array: the world-space AABB of the terrain that actually exists, and one
// contour-ring "island" per top-level region that actually owns hexes.
//
// Both answers deliberately come from the HEXES, not from `data.bounds` or
// `region.centroid`:
//
//  • `region.centroid` is a semantic-layout artefact. Most bakes contain
//    top-level regions whose whole subtree owns no hexes at all, and their
//    centroids can land far outside the terrain (the real bake has one at
//    x ≈ 80 with a hex field that stops at x = 39). Ringing those produced
//    concentric bullseyes on empty paper.
//  • Even for regions that DO own hexes, the centroid can drift several units
//    off the hexes it is supposed to circle, so the ring sat beside its island
//    instead of around it.
//
// `topLevelRegions.ts` drops phantom regions for medallions with an ANALOGOUS
// guard, not an identical one, and the difference is worth knowing: it filters
// on `peakHeight === 0`, which also throws away a subtree whose hexes are all
// zero-height — exactly the ownership-vs-elevation conflation regionTerrain.ts
// warns about. The islands here filter on `hexCountPerSlot === 0`, i.e. on
// actual hex ownership, so a real-but-flat region still gets its ring. That
// makes this the stricter, more correct of the two. On the current bake they
// agree on every region, so the divergence is latent rather than visible.

import type { RenderData } from '../types';
import { hexToWorld } from './hexGeometry';

const HEX_FIELDS_PER_HEX = 5;

/** Centre + radius of one contour-ring cluster, in world units. */
export type Island = { cx: number; cz: number; r: number };

export type PaperGeometry = {
  islands: Island[];
  /** World-space AABB of every hex in the bake. Zero-size when there are none. */
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
};

/** The slice of RenderData this needs — keeps fixtures small and honest. */
type HexSource = Pick<RenderData, 'hexes' | 'hexSize' | 'regions'>;

export function buildPaperGeometry(data: HexSource): PaperGeometry {
  const hexes = data.hexes;
  const hexCount = Math.floor(hexes.length / HEX_FIELDS_PER_HEX);
  const regions = data.regions;

  // Pre-walk regionIdx → topLevelIdx so a hex can be attributed in O(1).
  // Hop-bounded, like RegionLabels' identical walk: a malformed bake with a
  // parent cycle must terminate rather than hang, and an out-of-range
  // parentIdx must stop the walk rather than dereference undefined.
  const topOfRegion = new Int32Array(regions.length);
  for (let i = 0; i < regions.length; i++) {
    let cur = i;
    for (let hops = 0; hops < regions.length; hops++) {
      const parent = regions[cur].parentIdx;
      if (parent < 0 || parent >= regions.length) break;
      cur = parent;
    }
    topOfRegion[i] = cur;
  }
  const topToSlot = new Map<number, number>();
  for (let i = 0; i < regions.length; i++) {
    if (regions[i].level === 0) topToSlot.set(i, topToSlot.size);
  }
  const slotCount = topToSlot.size;

  const xs = new Float64Array(hexCount);
  const zs = new Float64Array(hexCount);
  const slotOfHex = new Int32Array(hexCount);
  const sumX = new Float64Array(slotCount);
  const sumZ = new Float64Array(slotCount);
  const hexCountPerSlot = new Int32Array(slotCount);

  let minX = Infinity;
  let maxX = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;

  // Pass 1 — world positions, terrain AABB, per-region hex centroid accumulator.
  for (let h = 0, i = 0; h < hexCount; h++, i += HEX_FIELDS_PER_HEX) {
    const [x, z] = hexToWorld(hexes[i], hexes[i + 1], data.hexSize);
    xs[h] = x;
    zs[h] = z;
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (z < minZ) minZ = z;
    if (z > maxZ) maxZ = z;

    const regionIdx = hexes[i + 2];
    let slot = -1;
    if (regionIdx >= 0 && regionIdx < regions.length) {
      slot = topToSlot.get(topOfRegion[regionIdx]) ?? -1;
    }
    slotOfHex[h] = slot;
    if (slot >= 0) {
      sumX[slot] += x;
      sumZ[slot] += z;
      hexCountPerSlot[slot] += 1;
    }
  }

  const centreX = new Float64Array(slotCount);
  const centreZ = new Float64Array(slotCount);
  for (let s = 0; s < slotCount; s++) {
    if (hexCountPerSlot[s] === 0) continue;
    centreX[s] = sumX[s] / hexCountPerSlot[s];
    centreZ[s] = sumZ[s] / hexCountPerSlot[s];
  }

  // Pass 2 — radius as the max distance from the region's OWN hex centroid.
  const maxR2 = new Float64Array(slotCount);
  for (let h = 0; h < hexCount; h++) {
    const s = slotOfHex[h];
    if (s < 0) continue;
    const dx = xs[h] - centreX[s];
    const dz = zs[h] - centreZ[s];
    const d2 = dx * dx + dz * dz;
    if (d2 > maxR2[s]) maxR2[s] = d2;
  }

  const islands: Island[] = [];
  for (let s = 0; s < slotCount; s++) {
    // Drop "phantom" regions whose subtree has no hexes: there is no terrain
    // to ring, and the region's centroid is not a place on the map. Same
    // REASON as buildTopLevelRegions(), stricter test — hex ownership rather
    // than `peakHeight === 0` (see the header note).
    if (hexCountPerSlot[s] === 0) continue;
    islands.push({
      cx: centreX[s],
      cz: centreZ[s],
      // Floor so a one-hex region still gets a small ring rather than a
      // degenerate zero-radius one.
      r: Math.max(Math.sqrt(maxR2[s]), data.hexSize * 1.5),
    });
  }

  if (hexCount === 0) {
    return { islands, minX: 0, maxX: 0, minZ: 0, maxZ: 0 };
  }
  return { islands, minX, maxX, minZ, maxZ };
}
