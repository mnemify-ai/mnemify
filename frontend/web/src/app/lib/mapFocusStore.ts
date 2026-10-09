import { create } from "zustand";
import { useMapHighlightStore } from "./mapHighlightStore";

/**
 * Region-focus bridge into the Home page's KnowledgeMap, as a module-level store
 * so surfaces that live outside HomePage (the Ask dock) can fly the camera.
 * Tag focus doesn't need this — it's URL-addressable via `?tag=` (useTagParam).
 *
 * A request made from another route survives the navigation to "/" because
 * the store outlives route mounts; HomePage consumes it on mount.
 */
type MapFocusState = {
  focusRegionId: string | null;
  setFocusRegion: (id: string | null) => void;
  /** Bumped by `requestFocus`, so asking for the region that's already
   *  focused still flies the camera back to it. */
  focusTick: number;
  /** Explicit "show me this region" from outside the map (a citation, a
   *  compile-report row, an evidence drawer). Unlike `setFocusRegion` — which
   *  is also the map's own store → prop echo — this always re-flies, and it
   *  outranks the pending Ask-highlight framing. */
  requestFocus: (id: string) => void;
  /** Nonce for "show me the whole map, from scratch": bumped by the brand
   *  mark in the top bar. KnowledgeMap watches it and runs `home()` — clears
   *  focus, tag, open doc and history, and re-frames the camera. */
  resetTick: number;
  requestReset: () => void;
};

export const useMapFocusStore = create<MapFocusState>((set) => ({
  focusRegionId: null,
  setFocusRegion: (focusRegionId) => set({ focusRegionId }),
  focusTick: 0,
  requestFocus: (focusRegionId) => {
    useMapHighlightStore.getState().claimCamera();
    set((s) => ({ focusRegionId, focusTick: s.focusTick + 1 }));
  },
  resetTick: 0,
  requestReset: () => set((s) => ({ focusRegionId: null, resetTick: s.resetTick + 1 })),
}));
