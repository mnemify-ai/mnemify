import type { RenderData, NotesFile, RegionEntry, Arc, Note } from "../../knowledgeMap/types";
import type { MapIndexes } from "./types";

const HEX_STRIDE = 5; // [q, r, regionIdx, height, tagIdx]

export function buildIndexes(renderData: RenderData, notesFile: NotesFile): MapIndexes {
  const regionsByIdx = renderData.regions;

  // 1. regionsById + regionPathById
  const regionsById = new Map<string, RegionEntry>();
  regionsByIdx.forEach((r) => regionsById.set(r.id, r));

  const regionPathByIdx = new Map<number, RegionEntry[]>();
  function pathForIdx(idx: number): RegionEntry[] {
    const cached = regionPathByIdx.get(idx);
    if (cached) return cached;
    const region = regionsByIdx[idx];
    const path =
      region.parentIdx === -1
        ? [region]
        : [...pathForIdx(region.parentIdx), region];
    regionPathByIdx.set(idx, path);
    return path;
  }
  const regionPathById = new Map<string, RegionEntry[]>();
  regionsByIdx.forEach((r, idx) => regionPathById.set(r.id, pathForIdx(idx)));

  const topLevelRegionByRegionId = new Map<string, RegionEntry>();
  regionPathById.forEach((path, regionId) => {
    topLevelRegionByRegionId.set(regionId, path[0]);
  });

  // 2. Hex-derived: per-tag spire region + height
  const regionByTagId = new Map<string, RegionEntry>();
  const tagHeights = new Map<string, number>();
  const hexes = renderData.hexes;
  for (let i = 0; i < hexes.length; i += HEX_STRIDE) {
    const tagIdx = hexes[i + 4];
    if (tagIdx < 0) continue; // filler hex
    const tagId = renderData.tagIndex[tagIdx];
    if (!tagId) continue;
    if (regionByTagId.has(tagId)) continue; // first match wins (one spire per tag)
    const regionIdx = hexes[i + 2];
    const height = hexes[i + 3];
    regionByTagId.set(tagId, regionsByIdx[regionIdx]);
    tagHeights.set(tagId, height);
  }

  // topLevelRegionByTagId
  const topLevelRegionByTagId = new Map<string, RegionEntry>();
  regionByTagId.forEach((leafRegion, tagId) => {
    const top = topLevelRegionByRegionId.get(leafRegion.id);
    if (top) topLevelRegionByTagId.set(tagId, top);
  });

  // 3. tagIdToIdx + tagLabelById (real LLM names; falls back to id if a stale
  //    render-data was baked before `tagLabels` existed).
  const tagIdToIdx = new Map<string, number>();
  const tagLabelById = new Map<string, string>();
  renderData.tagIndex.forEach((id, idx) => {
    tagIdToIdx.set(id, idx);
    const label = renderData.tagLabels?.[idx];
    if (label) tagLabelById.set(id, label);
  });

  // 4. arcsByTagId
  const arcsByTagId = new Map<string, Arc[]>();
  renderData.arcs.forEach((arc) => {
    pushTo(arcsByTagId, arc.fromTagId, arc);
    pushTo(arcsByTagId, arc.toTagId, arc);
  });

  // 5. Notes indexes
  const notes = notesFile.notes;
  const notesByTagId = new Map<string, Note[]>();
  const notesByRegionId = new Map<string, Note[]>();
  notes.forEach((n) => {
    n.tagIds.forEach((tid) => pushTo(notesByTagId, tid, n));
    pushTo(notesByRegionId, n.regionId, n);
  });

  // 6. notesByRegionSubtree — aggregate up the tree
  const childrenByParentIdx = new Map<number, number[]>();
  regionsByIdx.forEach((r, idx) => {
    if (r.parentIdx >= 0) pushTo(childrenByParentIdx, r.parentIdx, idx);
  });
  const subtreeCache = new Map<string, Note[]>();
  function subtreeFor(idx: number): Note[] {
    const region = regionsByIdx[idx];
    const cached = subtreeCache.get(region.id);
    if (cached) return cached;
    const own = notesByRegionId.get(region.id) ?? [];
    const childIdxs = childrenByParentIdx.get(idx) ?? [];
    if (childIdxs.length === 0) {
      subtreeCache.set(region.id, own);
      return own;
    }
    const combined: Note[] = [...own];
    childIdxs.forEach((cIdx) => combined.push(...subtreeFor(cIdx)));
    subtreeCache.set(region.id, combined);
    return combined;
  }
  regionsByIdx.forEach((_, idx) => subtreeFor(idx));

  // 7. Isolated tags — referenced by no arc
  const referenced = new Set<string>();
  renderData.arcs.forEach((a) => {
    referenced.add(a.fromTagId);
    referenced.add(a.toTagId);
  });
  const isolatedTagIds = renderData.tagIndex.filter((id) => !referenced.has(id));

  return {
    regionsByIdx,
    regionsById,
    regionPathById,
    topLevelRegionByTagId,
    topLevelRegionByRegionId,
    tagIdToIdx,
    tagLabelById,
    tagHeights,
    regionByTagId,
    arcsByTagId,
    notesByTagId,
    notesByRegionId,
    notesByRegionSubtree: subtreeCache,
    isolatedTagIds,
  };
}

function pushTo<K, V>(map: Map<K, V[]>, key: K, value: V) {
  const existing = map.get(key);
  if (existing) existing.push(value);
  else map.set(key, [value]);
}
