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
};

export const useMapFocusStore = create<MapFocusState>((set) => ({
  focusRegionId: null,
  setFocusRegion: (focusRegionId) => set({ focusRegionId }),
}));
