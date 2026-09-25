import { create } from "zustand";

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
  /** Nonce for "show me the whole map, from scratch": bumped by the brand
   *  mark in the top bar. KnowledgeMap watches it and runs `home()` — clears
   *  focus, tag, open doc and history, and re-frames the camera. */
  resetTick: number;
  requestReset: () => void;
};

export const useMapFocusStore = create<MapFocusState>((set) => ({
  focusRegionId: null,
  setFocusRegion: (focusRegionId) => set({ focusRegionId }),
  resetTick: 0,
  requestReset: () => set((s) => ({ focusRegionId: null, resetTick: s.resetTick + 1 })),
}));
