// Resolves the Ask dock's answer highlight (graph node ids off the wire) into
// what this bake can actually light: tag ids that have a spire, and region
// indices at any level. Notes have no hex of their own, so a note citation
// lights its primary tag's spire (falling back to every tag it carries).
//
// The hook keeps the per-mount map store in step with the app-level
// mapHighlightStore and frames the camera once per highlight token.

import { useEffect, useMemo, useRef } from 'react';
import { useMapHighlightStore, type MapHighlight } from '../../app/lib/mapHighlightStore';
import { useNotes } from '../data/useNotes';
import { useKnowledgeMapStore, type ResolvedHighlight } from '../store';
import type { Note, RenderData } from '../types';

/** Pure resolve. `notesById` may be null while the notes file is still
 *  loading — note citations are then simply not lit yet (the hook re-runs
 *  when notes land). */
export function resolveAskHighlight(
  data: RenderData,
  notesById: Map<string, Note> | null,
  h: MapHighlight,
): ResolvedHighlight {
  const tagOnMap = new Set(data.tagIndex);
  const tagIds = new Set<string>();
  for (const t of h.tagIds) if (tagOnMap.has(t)) tagIds.add(t);

  const regionIdxById = new Map<string, number>();
  for (let i = 0; i < data.regions.length; i++) regionIdxById.set(data.regions[i].id, i);
  const regionIdxs = new Set<number>();
  for (const r of h.regionIds) {
    const idx = regionIdxById.get(r);
    if (idx !== undefined) regionIdxs.add(idx);
  }

  if (notesById) {
    for (const n of h.noteIds) {
      const note = notesById.get(n);
      if (!note) continue;
      if (note.primaryTagId && tagOnMap.has(note.primaryTagId)) {
        tagIds.add(note.primaryTagId);
      } else {
        for (const t of note.tagIds) if (tagOnMap.has(t)) tagIds.add(t);
      }
      const ridx = regionIdxById.get(note.regionId);
      if (ridx !== undefined) regionIdxs.add(ridx);
    }
  }
  return { tagIds, regionIdxs, label: h.label, token: h.token };
}

/** Top-level region index shared by every highlighted tag/region, or null
 *  when the highlight spans several top-level regions (→ frame the whole
 *  map) or lights nothing this bake knows. */
export function highlightTopLevelIdx(
  data: RenderData,
  resolved: ResolvedHighlight,
): number | null | undefined {
  const topOf = (idx: number): number => {
    let cur = idx;
    for (let hops = 0; hops < data.regions.length; hops++) {
      const parent = data.regions[cur].parentIdx;
      if (parent < 0 || parent >= data.regions.length) break;
      cur = parent;
    }
    return cur;
  };
  const tops = new Set<number>();
  for (const idx of resolved.regionIdxs) tops.add(topOf(idx));
  if (resolved.tagIds.size > 0) {
    const wanted = new Set<number>();
    for (const t of resolved.tagIds) {
      const ti = data.tagIndex.indexOf(t);
      if (ti >= 0) wanted.add(ti);
    }
    const STRIDE = 5;
    for (let i = 0; i < data.hexes.length && wanted.size > 0; i += STRIDE) {
      const ti = data.hexes[i + 4];
      if (wanted.has(ti)) {
        tops.add(topOf(data.hexes[i + 2]));
        wanted.delete(ti);
      }
    }
  }
  if (tops.size === 0) return undefined;
  if (tops.size === 1) return [...tops][0];
  return null;
}

/** Mirror the app-level highlight into this map's store and fly the camera
 *  once per token. Mounted in KnowledgeMap's ReadyChrome (it needs the
 *  notes URL for note → tag resolution). */
export function useAskHighlightSync(data: RenderData, notesUrl: string) {
  const highlight = useMapHighlightStore((s) => s.highlight);
  const setAskHighlight = useKnowledgeMapStore((s) => s.setAskHighlight);
  const requestZoomToRegion = useKnowledgeMapStore((s) => s.requestZoomToRegion);

  // Notes are only needed when a highlight names notes — and then the same
  // module-level cache the tooltip uses serves them.
  const needNotes = highlight !== null && highlight.noteIds.length > 0;
  const notes = useNotes(notesUrl, needNotes);
  const notesById = useMemo(() => {
    if (notes.status !== 'ready') return null;
    const m = new Map<string, Note>();
    for (const n of notes.notes) m.set(n.id, n);
    return m;
  }, [notes]);

  const resolved = useMemo(
    () => (highlight ? resolveAskHighlight(data, notesById, highlight) : null),
    [data, notesById, highlight],
  );

  useEffect(() => {
    setAskHighlight(resolved);
  }, [resolved, setAskHighlight]);

  // One framing per token. Waits for note resolution when notes are the only
  // thing cited, so the camera goes where the spires actually are.
  const framedTokenRef = useRef<number | null>(null);
  useEffect(() => {
    if (!resolved) {
      framedTokenRef.current = null;
      return;
    }
    if (framedTokenRef.current === resolved.token) return;
    if (needNotes && notesById === null && resolved.tagIds.size === 0 && resolved.regionIdxs.size === 0) {
      return; // notes still loading — nothing to frame yet
    }
    const top = highlightTopLevelIdx(data, resolved);
    if (top === undefined) return;
    framedTokenRef.current = resolved.token;
    requestZoomToRegion(top);
  }, [resolved, data, needNotes, notesById, requestZoomToRegion]);
}
