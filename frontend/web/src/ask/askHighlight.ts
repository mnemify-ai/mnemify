// Pure: which graph nodes an answer's citations point at on the map. Kept out
// of useAskStream so it can be unit-tested without an SSE stream.

import type { Citation } from "./types";

export type HighlightIds = {
  tagIds: string[];
  regionIds: string[];
  noteIds: string[];
};

/** Tags, regions and notes named by `citations`, deduped in citation order.
 *
 *  - a tag citation lights its own spire;
 *  - a region citation lights that region;
 *  - a note citation lights the note (the map resolves it to its tag);
 *  - an entity / signal citation has no hex of its own, so it contributes its
 *    source notes and, failing that, its home region.
 *  Every citation's home region is also collected, so the medallion pulse and
 *  the camera framing see the full spread even when only notes were cited. */
export function highlightFromCitations(citations: readonly Citation[]): HighlightIds {
  const tags = new Set<string>();
  const regions = new Set<string>();
  const notes = new Set<string>();
  for (const c of citations) {
    if (c.node_type === "tag") tags.add(c.node_id);
    else if (c.node_type === "region") regions.add(c.node_id);
    else if (c.node_type === "note") notes.add(c.node_id);
    else {
      let any = false;
      for (const n of c.source_note_ids ?? []) {
        notes.add(n);
        any = true;
      }
      if (!any && c.home_region_id) regions.add(c.home_region_id);
    }
    if (c.home_region_id) regions.add(c.home_region_id);
  }
  return { tagIds: [...tags], regionIds: [...regions], noteIds: [...notes] };
}

/** The citations the answer actually referenced. With `fallback` the server
 *  picked `used` itself (top-scored), which is still the best guess. */
export function usedCitations(
  citations: readonly Citation[],
  used: readonly string[],
): Citation[] {
  if (used.length === 0) return [...citations];
  const keep = new Set(used);
  return citations.filter((c) => keep.has(c.citation_id));
}
