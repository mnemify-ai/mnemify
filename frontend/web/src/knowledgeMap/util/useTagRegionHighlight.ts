// Resolves the currently-selected tag's weighted top-level region memberships
// into a shape the popover + legend/medallion pulse can consume.
//
// `tagRegionWeights` (optional, baked by the backend) lists, per tag, the
// top-level regions it semantically resembles, each with a 0..1 weight and an
// `isHome` flag. The region indices are indices into `data.regions` and are
// always top-level. Returns empty maps when nothing is selected or the bake
// predates the field.

import { useMemo } from 'react';
import { useKnowledgeMapStore } from '../store';
import type { RenderData } from '../types';

export type TagRegionHighlight = {
  tagId: string | null;
  /** Top-level regionIdx that owns the tag's hex, or null. */
  homeIdx: number | null;
  /** regionIdx → weight for the OTHER regions the tag resembles (excludes home). */
  related: Map<number, number>;
  /** True when there's at least one related (non-home) region to surface. */
  hasRelated: boolean;
};

const EMPTY: TagRegionHighlight = {
  tagId: null,
  homeIdx: null,
  related: new Map(),
  hasRelated: false,
};

/** Pure resolver — exported for testing without the store context. */
export function computeTagRegionHighlight(
  data: RenderData,
  selectedTagId: string | null,
): TagRegionHighlight {
  if (!selectedTagId || !data.tagRegionWeights) return EMPTY;
  const tagIdx = data.tagIndex.indexOf(selectedTagId);
  if (tagIdx < 0) return EMPTY;
  const weights = data.tagRegionWeights[tagIdx];
  if (!weights || weights.length === 0) {
    return { tagId: selectedTagId, homeIdx: null, related: new Map(), hasRelated: false };
  }
  let homeIdx: number | null = null;
  const related = new Map<number, number>();
  for (const w of weights) {
    if (w.isHome) homeIdx = w.regionIdx;
    else related.set(w.regionIdx, w.weight);
  }
  return { tagId: selectedTagId, homeIdx, related, hasRelated: related.size > 0 };
}

export function useTagRegionHighlight(data: RenderData): TagRegionHighlight {
  const selectedTagId = useKnowledgeMapStore((s) => s.selectedTagId);
  return useMemo(
    () => computeTagRegionHighlight(data, selectedTagId),
    [selectedTagId, data],
  );
}
