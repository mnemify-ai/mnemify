import { create } from "zustand";

/**
 * How wide the map's right detail panel currently is, as a module-level
 * store so chrome mounted *outside* HomePage can stay clear of it.
 *
 * The panel is user-resizable, snaps narrower while the Ask dock is open, and
 * collapses to a rail — so the hardcoded 424px/324px mirrors of its width
 * that used to sit in HomePage went stale the moment anyone dragged it (and
 * a Tailwind class can't read a runtime number anyway). HomePage feeds this from
 * KnowledgeMap's `onPanelWidthChange`; the shell's Ask bubble and Home's briefing
 * card read it. 0 means "no map panel on screen" (any non-Home route, the
 * empty state, the demo terrain), which is exactly the right inset there too.
 */
type MapPanelState = {
  width: number;
  setWidth: (width: number) => void;
};

export const useMapPanelStore = create<MapPanelState>((set) => ({
  width: 0,
  setWidth: (width) => set({ width }),
}));

/** Gap between the panel's inner edge and chrome floated beside it. */
export const MAP_PANEL_GUTTER = 24;
