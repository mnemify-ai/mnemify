import { create } from "zustand";

/**
 * What the last Ask answer was grounded in, mirrored onto the 3D map.
 *
 * When `/api/ask` sends its `citations` event the dock publishes the cited
 * tags / regions / notes here; the map (HexField) lights those spires, dims
 * everything else and frames the camera on them. `citations_used` then
 * narrows the set to what the answer actually referenced. The highlight
 * stays until the next question, an Escape on the map, or the pill's ×.
 *
 * Module-level, like mapPulseStore: the Ask dock lives in the app shell and
 * unmounts when closed, while the map lives on Home. Ids here are graph node
 * ids straight off the wire — the map resolves them against its own bake.
 */
export type MapHighlight = {
  /** Tag node ids (== render-data `tagIndex` entries). */
  tagIds: string[];
  /** Region node ids (== render-data `regions[].id`). */
  regionIds: string[];
  /** Note ids (`n-…`, == mocknotes `notes[].id`); resolved to tags on the map. */
  noteIds: string[];
  /** The question this answers — shown on the map's "showing sources for" pill. */
  label: string;
  /** Bumped on every fresh highlight, NOT on a narrow: the map frames the
   *  camera once per token so the reconcile at the end of an answer never
   *  yanks the view a second time. */
  token: number;
};

type MapHighlightState = {
  highlight: MapHighlight | null;
  /** Publish a fresh highlight (new token → the map re-frames). */
  setHighlight: (h: Omit<MapHighlight, "token">) => void;
  /** Replace the id sets, keeping the token (no camera move). No-op when
   *  nothing is highlighted. */
  narrow: (h: Pick<MapHighlight, "tagIds" | "regionIds" | "noteIds">) => void;
  clear: () => void;
};

let nextToken = 1;

export const useMapHighlightStore = create<MapHighlightState>((set, get) => ({
  highlight: null,
  setHighlight: (h) => set({ highlight: { ...h, token: nextToken++ } }),
  narrow: (h) => {
    const cur = get().highlight;
    if (!cur) return;
    set({ highlight: { ...cur, ...h } });
  },
  clear: () => {
    if (get().highlight !== null) set({ highlight: null });
  },
}));
