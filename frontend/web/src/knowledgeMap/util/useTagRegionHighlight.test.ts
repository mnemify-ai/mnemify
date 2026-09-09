import { describe, it, expect } from 'vitest';
import { computeTagRegionHighlight } from './useTagRegionHighlight';
import type { RenderData } from '../types';

function makeData(tagRegionWeights?: RenderData['tagRegionWeights']): RenderData {
  return {
    version: 3,
    schemaName: 'cortex.brain-map.hex',
    generatedAt: '',
    bounds: { minX: 0, maxX: 1, minZ: 0, maxZ: 1, maxY: 1 },
    palette: { bg: '#000', ramp: [] },
    hexSize: 1,
    regions: [],
    hexes: [],
    tagIndex: ['tag.a', 'tag.b'],
    tagRecency: [0, 0],
    tagRegionWeights,
    arcs: [],
    highlights: { godTagIds: [], bridgeTagIds: [], trendingTagIds: [] },
    shaderParams: { warpAmp: 0, reachCapMultiplier: 0 },
  };
}

describe('computeTagRegionHighlight', () => {
  it('returns empty when nothing is selected', () => {
    const h = computeTagRegionHighlight(makeData([]), null);
    expect(h.tagId).toBeNull();
    expect(h.hasRelated).toBe(false);
  });

  it('returns empty when tagRegionWeights is absent (old bake)', () => {
    const h = computeTagRegionHighlight(makeData(undefined), 'tag.a');
    expect(h.hasRelated).toBe(false);
    expect(h.homeIdx).toBeNull();
  });

  it('splits home from related and flags hasRelated', () => {
    const data = makeData([
      [ // tag.a
        { regionIdx: 2, weight: 1.0, isHome: true },
        { regionIdx: 5, weight: 0.8, isHome: false },
        { regionIdx: 7, weight: 0.5, isHome: false },
      ],
      [], // tag.b
    ]);
    const h = computeTagRegionHighlight(data, 'tag.a');
    expect(h.homeIdx).toBe(2);
    expect(h.hasRelated).toBe(true);
    expect(h.related.get(5)).toBe(0.8);
    expect(h.related.get(7)).toBe(0.5);
    expect(h.related.has(2)).toBe(false); // home excluded from related
  });

  it('home-only tag has no related regions', () => {
    const data = makeData([[{ regionIdx: 0, weight: 1.0, isHome: true }], []]);
    const h = computeTagRegionHighlight(data, 'tag.a');
    expect(h.homeIdx).toBe(0);
    expect(h.hasRelated).toBe(false);
  });

  it('unknown tag id yields empty', () => {
    const h = computeTagRegionHighlight(makeData([[], []]), 'tag.missing');
    expect(h.hasRelated).toBe(false);
  });
});
