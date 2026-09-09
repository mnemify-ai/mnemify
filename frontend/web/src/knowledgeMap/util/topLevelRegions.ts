// Single-pass derivation of the per-top-level-region data both the
// medallion overlay (RegionLabels) and the parchment legend
// (RegionLegend) need: ordered top-level slot, summit position, and a
// "signature tag" used to disambiguate duplicated region names.
//
// Order is the natural order of `data.regions` filtered by `level === 0`
// — that's the order both medallions and legend rows index off, so the
// Roman numeral on each medallion matches its legend row.

import type { RenderData, RegionEntry } from '../types';
import { hexToWorld } from './hexGeometry';

const HEX_FIELDS_PER_HEX = 5;

export type TopLevelRegion = {
  idx: number;                       // index into data.regions
  region: RegionEntry;
  number: number;                    // 1-based slot — feeds toRoman()
  /** World-space position of the tallest hex in this region's subtree. */
  peak: { x: number; y: number; z: number };
  /** Most-prevalent tag id within this region's subtree, or null. */
  signatureTagId: string | null;
  /** Hexes in this region's subtree — its footprint on the map. */
  hexCount: number;
  /** How much this region "stands out": tallest peak weighted by footprint.
   *  Drives which handful of regions get an always-on label at rest
   *  (scene/RegionLabels.tsx). Higher = more prominent. */
  prominence: number;
};

export function buildTopLevelRegions(data: RenderData): TopLevelRegion[] {
  const tops: number[] = [];
  for (let i = 0; i < data.regions.length; i++) {
    if (data.regions[i].level === 0) tops.push(i);
  }
  if (tops.length === 0) return [];

  // O(1) regionIdx → topRegionIdx.
  const topOfRegion = new Int32Array(data.regions.length);
  for (let i = 0; i < data.regions.length; i++) {
    let cur = i;
    while (data.regions[cur].parentIdx >= 0) cur = data.regions[cur].parentIdx;
    topOfRegion[i] = cur;
  }

  const slotOf = new Map<number, number>();
  tops.forEach((idx, slot) => slotOf.set(idx, slot));

  const peakHeight = new Float32Array(tops.length);
  const peakX = new Float32Array(tops.length);
  const peakZ = new Float32Array(tops.length);
  const hexCount = new Int32Array(tops.length);
  const tagCounts: Array<Map<number, number>> = tops.map(() => new Map());

  const hexes = data.hexes;
  for (let i = 0; i < hexes.length; i += HEX_FIELDS_PER_HEX) {
    const regionIdx = hexes[i + 2];
    if (regionIdx < 0) continue;
    const slot = slotOf.get(topOfRegion[regionIdx]);
    if (slot === undefined) continue;
    hexCount[slot] += 1;
    const h = hexes[i + 3];
    if (h > peakHeight[slot]) {
      peakHeight[slot] = h;
      const [x, z] = hexToWorld(hexes[i], hexes[i + 1], data.hexSize);
      peakX[slot] = x;
      peakZ[slot] = z;
    }
    const tagIdx = hexes[i + 4];
    if (tagIdx >= 0) {
      const m = tagCounts[slot];
      m.set(tagIdx, (m.get(tagIdx) ?? 0) + 1);
    }
  }

  // Drop "phantom" regions whose subtree has no hexes — `peakHeight` stays
  // at the initial 0 in that case and we'd otherwise plot a medallion at
  // world origin (the "XIII floating in dead space" bug). After filtering,
  // Roman numerals re-pack into the contiguous 1..N visible set.
  const result: TopLevelRegion[] = [];
  let visibleSlot = 0;
  tops.forEach((idx, slot) => {
    if (peakHeight[slot] === 0) return;
    const m = tagCounts[slot];
    let topTagIdx = -1;
    let topTagCount = 0;
    m.forEach((count, tagIdx) => {
      if (count > topTagCount) {
        topTagCount = count;
        topTagIdx = tagIdx;
      }
    });
    visibleSlot += 1;
    result.push({
      idx,
      region: data.regions[idx],
      number: visibleSlot,
      peak: { x: peakX[slot], y: peakHeight[slot], z: peakZ[slot] },
      signatureTagId: topTagIdx >= 0 ? data.tagIndex[topTagIdx] : null,
      hexCount: hexCount[slot],
      prominence: peakHeight[slot] * (1 + Math.log(hexCount[slot])),
    });
  });
  return result;
}

/** "tag.ocr-accuracy" → "OCR Accuracy". Fallback only — used when the bake
 *  carries no real label for a tag id. */
export function prettifyTagId(tagId: string): string {
  const slug = tagId.startsWith('tag.') ? tagId.slice(4) : tagId;
  return slug
    .split(/[-_.]/)
    .map((part) =>
      /^[A-Z0-9]+$/.test(part) ? part : part.charAt(0).toUpperCase() + part.slice(1),
    )
    .join(' ');
}

/** The real LLM-generated label for a tag id, read from the bake's `tagLabels`
 *  array. Falls back to prettifying the id only when no label was baked (old
 *  render-data). This is the single source of truth for "what to show for a
 *  tag id" across the knowledge-map chrome. */
export function resolveTagLabel(data: RenderData, tagId: string): string {
  const idx = data.tagIndex.indexOf(tagId);
  const baked = idx >= 0 ? data.tagLabels?.[idx] : undefined;
  return baked && baked.trim().length > 0 ? baked : prettifyTagId(tagId);
}
