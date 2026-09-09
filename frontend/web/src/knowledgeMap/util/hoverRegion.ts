// "Which region is the pointer really over?" — resolved to the level the user
// is currently looking at.
//
// Hexes carry LEAF region indices, but the map is browsed one hierarchy level
// at a time: at the map root you see top-level regions, inside a region you
// see its immediate children. Hover feedback (terrain brighten, sidebar row,
// on-map label, preview card) must therefore land on the immediate child of
// the OPEN region that contains the hovered hex — never on the leaf itself,
// and never on a region the user can't currently see as a unit.
//
// Two hover sources feed the same answer:
//   • terrain — `hoveredHexMeta.regionIdx` (a leaf) resolved via
//     `resolveHoverChild`.
//   • sidebar — `legendHoverIdx`, set by the row / label under the cursor,
//     which is already a region at the current level.
// Terrain wins when both are set (a lingering sidebar hover after the pointer
// has moved onto the canvas is the only realistic overlap).

import { useMemo } from 'react';
import { useKnowledgeMapStore } from '../store';
import type { RenderData } from '../types';
import { regionTerrainFor } from './regionTerrain';

/**
 * Immediate child of `focusIdx` on the ancestor chain of `leafIdx`, or the
 * top-level ancestor when nothing is focused. Returns null when the hex is
 * outside the focused region's subtree (unrelated terrain reads as
 * background) or IS the focused region's own terrain (there is no child to
 * highlight — the focused region is already the whole stage).
 */
export function resolveHoverChild(
  ancestorsOf: number[][],
  leafIdx: number | null,
  focusIdx: number | null,
): number | null {
  if (leafIdx === null) return null;
  const chain = ancestorsOf[leafIdx];   // self → parent → … → root
  if (!chain || chain.length === 0) return null;
  if (focusIdx === null) return chain[chain.length - 1];
  const at = chain.indexOf(focusIdx);
  if (at <= 0) return null;             // unrelated branch, or the focus itself
  return chain[at - 1];
}

export type HoverRegion = {
  /** Region at the current level under the pointer (terrain or sidebar). */
  idx: number | null;
  source: 'terrain' | 'sidebar' | null;
};

const NONE: HoverRegion = { idx: null, source: null };

export function useHoverRegion(data: RenderData): HoverRegion {
  const focusRegionIdx = useKnowledgeMapStore((s) => s.focusRegionIdx);
  const hoveredLeaf = useKnowledgeMapStore((s) => s.hoveredHexMeta?.regionIdx ?? null);
  const legendHoverIdx = useKnowledgeMapStore((s) => s.legendHoverIdx);
  return useMemo(() => {
    const { ancestorsOf } = regionTerrainFor(data);
    const fromTerrain = resolveHoverChild(ancestorsOf, hoveredLeaf, focusRegionIdx);
    if (fromTerrain !== null) return { idx: fromTerrain, source: 'terrain' };
    if (legendHoverIdx !== null && legendHoverIdx >= 0 && legendHoverIdx < data.regions.length) {
      return { idx: legendHoverIdx, source: 'sidebar' };
    }
    return NONE;
  }, [data, hoveredLeaf, focusRegionIdx, legendHoverIdx]);
}
