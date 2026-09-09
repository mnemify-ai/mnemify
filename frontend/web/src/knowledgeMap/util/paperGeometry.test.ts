import { describe, expect, it } from 'vitest';
import { buildPaperGeometry } from './paperGeometry';
import type { RegionEntry } from '../types';

const HEX_SIZE = 0.5;

function region(
  over: Partial<RegionEntry> & { level: number; parentIdx: number },
): RegionEntry {
  return {
    id: 'r',
    name: 'r',
    isLeaf: true,
    color: '#000',
    accent: null,
    centroid: { x: 0, z: 0 },
    radius: 1,
    basePlateauHeight: 0,
    tagCount: 0,
    avgElevation: 0,
    ...over,
  };
}

describe('buildPaperGeometry', () => {
  it('skips top-level regions whose subtree owns no hexes', () => {
    const regions = [
      // 0: owns hexes via its child (2)
      region({ level: 0, parentIdx: -1 }),
      // 1: phantom — centroid parked far off the terrain, no hexes anywhere
      region({ level: 0, parentIdx: -1, centroid: { x: 400, z: -400 } }),
      region({ level: 1, parentIdx: 0 }),
    ];
    const hexes = [
      // q, r, regionIdx, height, tagIdx
      0, 0, 2, 1, -1,
      1, 0, 2, 1, -1,
    ];

    const geom = buildPaperGeometry({ hexes, hexSize: HEX_SIZE, regions });

    expect(geom.islands).toHaveLength(1);
    // The phantom's x=400 must not leak into the ring set or the extent.
    expect(geom.maxX).toBeLessThan(10);
    expect(geom.islands[0].cx).toBeCloseTo(0.5, 6);
  });

  it('centres an island on its hexes, not on region.centroid', () => {
    const regions = [region({ level: 0, parentIdx: -1, centroid: { x: 30, z: 30 } })];
    // Two hexes at world x = 0 and x = 2 (q=0 and q=2, r=0), both z = 0.
    const hexes = [0, 0, 0, 1, -1, 2, 0, 0, 1, -1];

    const geom = buildPaperGeometry({ hexes, hexSize: HEX_SIZE, regions });

    expect(geom.islands).toHaveLength(1);
    expect(geom.islands[0].cx).toBeCloseTo(1, 6);
    expect(geom.islands[0].cz).toBeCloseTo(0, 6);
    // Radius spans the hexes from that centre, not from (30, 30).
    expect(geom.islands[0].r).toBeCloseTo(1, 6);
  });

  it('gives a single-hex region a small floored radius', () => {
    const regions = [region({ level: 0, parentIdx: -1 })];
    const hexes = [3, 0, 0, 1, -1];

    const geom = buildPaperGeometry({ hexes, hexSize: HEX_SIZE, regions });

    expect(geom.islands[0].r).toBeCloseTo(HEX_SIZE * 1.5, 6);
  });

  it('reports the hex AABB per axis', () => {
    const regions = [region({ level: 0, parentIdx: -1 })];
    // q=0,r=0 → (0, 0); q=4,r=0 → (4, 0); q=0,r=2 → (1, 2*0.5*sqrt3)
    const hexes = [0, 0, 0, 1, -1, 4, 0, 0, 1, -1, 0, 2, 0, 1, -1];

    const geom = buildPaperGeometry({ hexes, hexSize: HEX_SIZE, regions });

    expect(geom.minX).toBeCloseTo(0, 6);
    expect(geom.maxX).toBeCloseTo(4, 6);
    expect(geom.minZ).toBeCloseTo(0, 6);
    expect(geom.maxZ).toBeCloseTo(Math.sqrt(3), 6);
  });

  it('survives an empty hex field', () => {
    const geom = buildPaperGeometry({ hexes: [], hexSize: HEX_SIZE, regions: [] });
    expect(geom.islands).toEqual([]);
    expect(geom).toMatchObject({ minX: 0, maxX: 0, minZ: 0, maxZ: 0 });
  });

  // The regionIdx → top-level walk is hop-bounded (same shape as RegionLabels'),
  // so a malformed bake degrades instead of locking the tab. Reaching the
  // assertions AT ALL is the real check: an unguarded walk spins forever inside
  // the synchronous call and no test timeout can interrupt it.
  it('survives a parent cycle instead of hanging', () => {
    const regions = [
      // 0: healthy top-level, owns its own hexes.
      region({ level: 0, parentIdx: -1 }),
      // 1 ↔ 2: parent chain loops back on itself.
      region({ level: 0, parentIdx: 2 }),
      region({ level: 1, parentIdx: 1 }),
    ];
    const hexes = [
      // q, r, regionIdx, height, tagIdx
      0, 0, 0, 1, -1,
      2, 0, 0, 1, -1,
      6, 0, 2, 1, -1,
    ];

    const geom = buildPaperGeometry({ hexes, hexSize: HEX_SIZE, regions });

    // The healthy region still rings its own hexes (world x = 0 and 2).
    expect(geom.islands.length).toBeGreaterThanOrEqual(1);
    expect(geom.islands[0].cx).toBeCloseTo(1, 6);
    // …and the AABB still covers every hex, the cycle's included.
    expect(geom.maxX).toBeCloseTo(6, 6);
  });

  // Same guard, other failure mode: an unbounded walk would deref
  // `regions[99]` and throw before it ever got the chance to loop.
  it('survives an out-of-range parentIdx', () => {
    const regions = [
      region({ level: 0, parentIdx: 99 }),
      region({ level: 1, parentIdx: 0 }),
    ];
    const hexes = [0, 0, 1, 1, -1, 2, 0, 1, 1, -1];

    const geom = buildPaperGeometry({ hexes, hexSize: HEX_SIZE, regions });

    expect(geom.islands).toHaveLength(1);
    expect(geom.islands[0].cx).toBeCloseTo(1, 6);
  });
});
