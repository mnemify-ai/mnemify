// Per-mount zustand store factory + React context provider.
// Each <KnowledgeMap /> creates its own store so multiple maps on a page
// don't share state, and the store has no module-level singleton.

import { createContext, createElement, useContext, useRef, type ReactNode } from 'react';
import { createStore, useStore } from 'zustand';

/** What HexField resolves about the hovered hex, surfaced for the tooltip
 *  overlay. Decoupled from `hoveredInstanceId` (which is just the raycaster
 *  id) so the tooltip never has to reach back into HexField's instanceLookup. */
export type HoveredHexMeta = {
  /** Region the hovered hex belongs to. */
  regionIdx: number;
  /** Tag id, or null if this hex is plain region terrain (not a tag spire). */
  tagId: string | null;
};

/** A point in the right-panel navigation history. Region focus + selected tag +
 *  open document together describe "which screen" the panel is showing, so a
 *  single snapshot can be restored by Back. */
export type NavSnapshot = {
  focusRegionIdx: number | null;
  selectedTagId: string | null;
  docNoteId: string | null;
};

export type FocusState = {
  /** null = map root (top-level) scope. Otherwise an index into RegionEntry[]. */
  focusRegionIdx: number | null;
  /** Currently selected tag (null = none). */
  selectedTagId: string | null;
  /** Note whose full document is open in the right panel (null = none). */
  docNoteId: string | null;
  /** Back-stack of prior nav snapshots. Only `navigate`/`back` write it. */
  navHistory: NavSnapshot[];
  /** Hex hovered by the cursor, as InstancedMesh instance id. Null = none. */
  hoveredInstanceId: number | null;
  /** Resolved meta (tag + region) for the hovered hex. Null when no hover. */
  hoveredHexMeta: HoveredHexMeta | null;
  /** Region idx hovered in the right panel (a top-level row at the map root,
   *  a sub-region row inside a focused region) or on an on-map label, or null.
   *  Always a region at the CURRENT browsing level — see util/hoverRegion.ts,
   *  which merges it with the terrain hover. Purely presentational: it lights
   *  the region's terrain footprint, its on-map label and its sidebar row. */
  legendHoverIdx: number | null;
  /** One-shot camera framing request. Fired by map clicks (hex / medallion)
   *  AND by any nav action that changes focus — including clearing focus back
   *  to the map root, where `idx: null` means "frame the whole map" (home).
   *  `tick` increments each request so CameraAnimator runs a single,
   *  time-bounded move and then fully releases — the camera never auto-snaps
   *  persistently, and the move is cancelled the instant the user grabs the
   *  controls. Nav actions that leave focus untouched (tag/doc only) emit
   *  nothing, so Escape on a tag never moves the camera. */
  zoomToRegion: { idx: number | null; tick: number } | null;
  /** tag.id → its summit-hex world position (tallest hex carrying that tag).
   *  Built once by HexField on data load so overlays (e.g. the tag-relation
   *  popover) can anchor to a tag without reaching into HexField internals. */
  tagSummitPos: Map<string, { x: number; y: number; z: number }>;
};

export type KnowledgeMapState = FocusState & {
  setFocusRegion: (idx: number | null) => void;
  setSelectedTag: (id: string | null) => void;
  setHoveredInstance: (id: number | null) => void;
  setHoveredHexMeta: (meta: HoveredHexMeta | null) => void;
  /** Request a one-shot camera move: to a region, or to the home framing
   *  when `idx` is null. */
  requestZoomToRegion: (idx: number | null) => void;
  /** Set/clear the sidebar/label-hovered region (any level). */
  setLegendHover: (idx: number | null) => void;
  setTagSummitPos: (m: Map<string, { x: number; y: number; z: number }>) => void;
  /** The single nav layer. Pushes the current snapshot to history, applies the
   *  patch atomically, and (by default) zooms the map when focus changes. This
   *  is the ONLY thing that should write focus/tag/doc from UI navigation. */
  navigate: (next: Partial<NavSnapshot>, opts?: { zoom?: boolean }) => void;
  /** Pop history: restore the previous snapshot and re-frame it (a region,
   *  or the whole map when the restored scope is the map root). */
  back: () => void;
  /** Clear to the map root (home) view. Escape semantics: only re-frames
   *  the camera when a region was actually focused. */
  resetNav: () => void;
  /** User-invoked "show me the whole map": clear nav to the root AND always
   *  re-frame the camera to the home framing — even when already at the root,
   *  because the user may have orbited or panned away from the overview and
   *  there is no other way to get it back. */
  home: () => void;
};

export type KnowledgeMapStore = ReturnType<typeof createKnowledgeMapStore>;

export function createKnowledgeMapStore(initial?: Partial<FocusState>) {
  return createStore<KnowledgeMapState>((set) => ({
    focusRegionIdx: initial?.focusRegionIdx ?? null,
    selectedTagId: initial?.selectedTagId ?? null,
    docNoteId: initial?.docNoteId ?? null,
    navHistory: initial?.navHistory ?? [],
    hoveredInstanceId: initial?.hoveredInstanceId ?? null,
    hoveredHexMeta: initial?.hoveredHexMeta ?? null,
    legendHoverIdx: initial?.legendHoverIdx ?? null,
    zoomToRegion: initial?.zoomToRegion ?? null,
    tagSummitPos: initial?.tagSummitPos ?? new Map(),
    setFocusRegion: (idx) => set({ focusRegionIdx: idx }),
    setSelectedTag: (id) => set({ selectedTagId: id }),
    setHoveredInstance: (id) => set({ hoveredInstanceId: id }),
    setHoveredHexMeta: (meta) => set({ hoveredHexMeta: meta }),
    setLegendHover: (idx) => set({ legendHoverIdx: idx }),
    requestZoomToRegion: (idx) =>
      set((s) => ({ zoomToRegion: { idx, tick: (s.zoomToRegion?.tick ?? 0) + 1 } })),
    setTagSummitPos: (m) => set({ tagSummitPos: m }),
    navigate: (next, opts) =>
      set((s) => {
        const cur: NavSnapshot = {
          focusRegionIdx: s.focusRegionIdx,
          selectedTagId: s.selectedTagId,
          docNoteId: s.docNoteId,
        };
        const merged: NavSnapshot = { ...cur, ...next };
        const changed =
          merged.focusRegionIdx !== cur.focusRegionIdx ||
          merged.selectedTagId !== cur.selectedTagId ||
          merged.docNoteId !== cur.docNoteId;
        if (!changed) return {};
        const focusChanged = merged.focusRegionIdx !== cur.focusRegionIdx;
        const patch: Partial<KnowledgeMapState> = {
          focusRegionIdx: merged.focusRegionIdx,
          selectedTagId: merged.selectedTagId,
          docNoteId: merged.docNoteId,
          navHistory: [...s.navHistory, cur],
        };
        if (focusChanged && (opts?.zoom ?? true)) {
          patch.zoomToRegion = { idx: merged.focusRegionIdx, tick: (s.zoomToRegion?.tick ?? 0) + 1 };
        }
        return patch;
      }),
    back: () =>
      set((s) => {
        if (s.navHistory.length === 0) return {};
        const prev = s.navHistory[s.navHistory.length - 1];
        const patch: Partial<KnowledgeMapState> = {
          focusRegionIdx: prev.focusRegionIdx,
          selectedTagId: prev.selectedTagId,
          docNoteId: prev.docNoteId,
          navHistory: s.navHistory.slice(0, -1),
        };
        // Only re-frame when Back actually moves the scope: a tag selected at
        // root pushes a null→null focus snapshot, and re-framing home for that
        // would yank the camera out of wherever the user parked it.
        if (prev.focusRegionIdx !== s.focusRegionIdx) {
          patch.zoomToRegion = { idx: prev.focusRegionIdx, tick: (s.zoomToRegion?.tick ?? 0) + 1 };
        }
        return patch;
      }),
    resetNav: () =>
      set((s) => ({
        focusRegionIdx: null,
        selectedTagId: null,
        docNoteId: null,
        navHistory: [],
        // Escape that only clears a tag must not move the camera; Escape that
        // drills out of a region frames the map back home.
        ...(s.focusRegionIdx !== null
          ? { zoomToRegion: { idx: null, tick: (s.zoomToRegion?.tick ?? 0) + 1 } }
          : {}),
      })),
    home: () =>
      set((s) => ({
        focusRegionIdx: null,
        selectedTagId: null,
        docNoteId: null,
        navHistory: [],
        zoomToRegion: { idx: null, tick: (s.zoomToRegion?.tick ?? 0) + 1 },
      })),
  }));
}

const KnowledgeMapStoreContext = createContext<KnowledgeMapStore | null>(null);

export function KnowledgeMapStoreProvider({
  store,
  children,
}: {
  store: KnowledgeMapStore;
  children: ReactNode;
}) {
  return createElement(KnowledgeMapStoreContext.Provider, { value: store }, children);
}

/** Hook to read/subscribe to the nearest <KnowledgeMap />'s store. */
export function useKnowledgeMapStore<T>(selector: (s: KnowledgeMapState) => T): T {
  const store = useContext(KnowledgeMapStoreContext);
  if (!store) {
    throw new Error('useKnowledgeMapStore must be used inside <KnowledgeMap />');
  }
  return useStore(store, selector);
}

/** Convenience hook that creates the store on first render and reuses it. */
export function useLocalKnowledgeMapStore(initial?: Partial<FocusState>): KnowledgeMapStore {
  const ref = useRef<KnowledgeMapStore | null>(null);
  if (ref.current === null) {
    ref.current = createKnowledgeMapStore(initial);
  }
  return ref.current;
}
