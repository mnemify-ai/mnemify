// The crux of the "clicking a chat citation greys the whole map and flies
// nowhere" fix: a region's OWN index is not a safe stand-in for the terrain it
// occupies, because a real bake carries regions whose whole subtree owns zero
// hexes. Everything here pins the resolve/peak contract both HexField's dim and
// CameraAnimator's framing now depend on.

import { describe, expect, it } from "vitest";
import { buildAncestorChains, buildRegionTerrain } from "./regionTerrain";
import type { RenderData, RegionEntry } from "../types";

const region = (id: string, parentIdx: number, level: number): RegionEntry =>
  ({
    id,
    name: id,
    level,
    parentIdx,
    isLeaf: true,
    color: "#000",
    accent: null,
    centroid: { x: 0, z: 0 },
    radius: 1,
    basePlateauHeight: 1,
    tagCount: 0,
    avgElevation: 0,
  }) as RegionEntry;

/**
 * regions:
 *   0 top_a          — owns hexes only through its descendants
 *     1 child_a      — owns hexes directly
 *       2 grandchild_a — hexless
 *     3 child_b      — hexless, but ancestor 0 has terrain
 *   4 top_b          — hexless, and no ancestor has terrain either
 *
 * hexes: [q, r, regionIdx, height, tagIdx], apothem 1 → hexToWorld(q,r,1).
 */
function fixture(hexes: number[] = [0, 0, 1, 5, -1, 2, 0, 1, 9, -1, 1, 0, 1, 3, -1]): RenderData {
  return {
    hexSize: 1,
    regions: [
      region("top_a", -1, 0),
      region("child_a", 0, 1),
      region("grandchild_a", 1, 2),
      region("child_b", 0, 1),
      region("top_b", -1, 0),
    ],
    hexes,
  } as unknown as RenderData;
}

describe("buildAncestorChains", () => {
  it("lists self first and the root last", () => {
    const chains = buildAncestorChains(fixture().regions);
    expect(chains[2]).toEqual([2, 1, 0]);
    expect(chains[0]).toEqual([0]);
  });

  it("survives a parent cycle instead of hanging", () => {
    const data = fixture();
    data.regions[0].parentIdx = 1; // top_a ↔ child_a cycle
    const chains = buildAncestorChains(data.regions);
    expect(chains[2]).toEqual([2, 1, 0]); // stops at the revisit of 1
    expect(chains[1]).toEqual([1, 0]);
  });
});

describe("resolveTerrainRegionIdx", () => {
  it("keeps a region that owns hexes itself", () => {
    const t = buildRegionTerrain(fixture());
    expect(t.resolveTerrainRegionIdx(1)).toBe(1);
    // Ownership is by subtree, so the parent counts as owning too.
    expect(t.resolveTerrainRegionIdx(0)).toBe(0);
  });

  it("climbs a hexless region to its nearest ancestor with terrain", () => {
    const t = buildRegionTerrain(fixture());
    // grandchild_a has no hexes of its own; child_a does.
    expect(t.resolveTerrainRegionIdx(2)).toBe(1);
    // child_b has none and neither does any sibling under it — top_a does.
    expect(t.resolveTerrainRegionIdx(3)).toBe(0);
  });

  it("returns null when no ancestor owns any hexes", () => {
    const t = buildRegionTerrain(fixture());
    // This is the "don't grey the world, don't fly to empty ground" case.
    expect(t.resolveTerrainRegionIdx(4)).toBeNull();
    expect(t.hasTerrain(4)).toBe(false);
  });

  it("returns null for null and for out-of-range indices", () => {
    const t = buildRegionTerrain(fixture());
    // A stale chat citation against a re-baked map must not throw.
    expect(t.resolveTerrainRegionIdx(null)).toBeNull();
    expect(t.resolveTerrainRegionIdx(99)).toBeNull();
    expect(t.resolveTerrainRegionIdx(-1)).toBeNull();
  });

  it("survives a parent cycle instead of hanging", () => {
    const data = fixture([0, 0, 2, 5, -1]); // only grandchild_a owns a hex
    data.regions[0].parentIdx = 1;          // top_a ↔ child_a cycle
    const t = buildRegionTerrain(data);
    expect(t.resolveTerrainRegionIdx(2)).toBe(2);
    // 3's chain is [3, 0, 1] — the cycle terminates and 0 answers first.
    expect(t.resolveTerrainRegionIdx(3)).toBe(0);
    expect(t.resolveTerrainRegionIdx(4)).toBeNull();
  });
});

describe("peakOf", () => {
  it("picks the tallest hex anywhere in the subtree", () => {
    const t = buildRegionTerrain(fixture());
    // The h=9 hex at (q=2, r=0) belongs to child_a, so both it and top_a peak
    // there — the whole point of attributing a hex to its ancestor chain.
    expect(t.peakOf(1)).toEqual({ x: 4, y: 9, z: 0 });
    expect(t.peakOf(0)).toEqual({ x: 4, y: 9, z: 0 });
  });

  it("prefers a descendant's taller hex over the parent's own", () => {
    //             q  r  reg  h  tag
    const data = fixture([0, 0, 0, 4, -1, 0, 0, 2, 12, -1]);
    const t = buildRegionTerrain(data);
    expect(t.peakOf(0)?.y).toBe(12);
    expect(t.peakOf(2)?.y).toBe(12);
  });

  it("is null for a subtree with no hexes", () => {
    const t = buildRegionTerrain(fixture());
    expect(t.peakOf(2)).toBeNull();
    expect(t.peakOf(4)).toBeNull();
  });

  it("counts a zero-height hex as real terrain", () => {
    // `topLevelRegions` treats peakHeight === 0 as "phantom"; the resolve must
    // not, or a flat subtree would silently climb to its parent.
    const t = buildRegionTerrain(fixture([0, 0, 3, 0, -1]));
    expect(t.hasTerrain(3)).toBe(true);
    expect(t.resolveTerrainRegionIdx(3)).toBe(3);
    expect(t.peakOf(3)).toEqual({ x: 0, y: 0, z: 0 });
  });
});

describe("hexCountOf / childrenOf", () => {
  it("counts a subtree's hexes on every ancestor", () => {
    const t = buildRegionTerrain(fixture());
    expect(t.hexCountOf(1)).toBe(3);   // child_a owns all three directly
    expect(t.hexCountOf(0)).toBe(3);   // …and top_a inherits them
    expect(t.hexCountOf(2)).toBe(0);
    expect(t.hexCountOf(4)).toBe(0);
    expect(t.hexCountOf(-1)).toBe(0);
  });

  it("lists immediate children in region order", () => {
    const t = buildRegionTerrain(fixture());
    expect(t.childrenOf(0)).toEqual([1, 3]);
    expect(t.childrenOf(1)).toEqual([2]);
    expect(t.childrenOf(4)).toEqual([]);
    expect(t.childrenOf(42)).toEqual([]);
  });
});
