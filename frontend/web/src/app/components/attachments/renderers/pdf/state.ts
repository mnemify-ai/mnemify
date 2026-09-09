// Reducer for the PDF viewer.
//
// The renderer juggles ~14 concerns (zoom mode + value, per-page rotation,
// search, sidebar, indexing progress, print dialog, password prompt,
// load progress…). A reducer keeps those transitions in one place and
// makes intent explicit at call sites: `dispatch({ type: "rotatePage", n })`
// reads better than four chained useState setters.
//
// What's NOT in here: refs (containerWidthRef, aliveRef), the virtualizers,
// the AbortController. Those are imperative bits that don't belong in state.

import type { Match } from "./searchIndex";

export type ZoomMode = "fitWidth" | "fitPage" | "actual" | "custom";
export type Rotation = 0 | 90 | 180 | 270;

export interface NaturalSize {
  width: number;
  height: number;
}

export interface SearchState {
  open: boolean;
  /** Bumps on every `openSearch` dispatch (even when already open) so the
   *  SearchPanel can re-focus / re-select the input on repeated Cmd-F. */
  openVersion: number;
  query: string;
  matches: Match[];
  /** -1 when there are no matches or none active yet. */
  activeIndex: number;
}

export interface PdfState {
  numPages: number | null;
  natural: NaturalSize | null;
  /** The first page's intrinsic /Rotate (0/90/180/270). `natural` is measured
   *  via getViewport(), which already bakes this in, so the render must apply
   *  the SAME rotation (intrinsic + any user rotation) or the layout box and
   *  the rendered canvas disagree and leave dead space. */
  naturalRotation: Rotation;
  zoomMode: ZoomMode;
  zoom: number;
  /** Per-page rotation. Missing key → 0. Empty by default. */
  rotations: Record<number, Rotation>;
  currentPage: number;
  sidebarOpen: boolean;
  search: SearchState;
  /** null when not indexing; otherwise {done, total} for progress UI. */
  indexing: { done: number; total: number } | null;
  /** Bumps when the search index is rebuilt (e.g. after indexing completes).
   *  Search-match-recompute effect listens to this so a query typed mid-
   *  indexing produces matches once the index lands. */
  indexVersion: number;
  printOpen: boolean;
  loadError: Error | null;
  password: string | null;
  pendingPassword: {
    callback: (pw: string) => void;
    reason: number;
  } | null;
  progress: { loaded: number; total: number } | null;
}

export const initialPdfState: PdfState = {
  numPages: null,
  natural: null,
  naturalRotation: 0,
  zoomMode: "fitWidth",
  zoom: 1,
  rotations: {},
  currentPage: 1,
  sidebarOpen: true,
  search: { open: false, openVersion: 0, query: "", matches: [], activeIndex: -1 },
  indexing: null,
  indexVersion: 0,
  printOpen: false,
  loadError: null,
  password: null,
  pendingPassword: null,
  progress: null,
};

export type PdfAction =
  | { type: "docLoaded"; numPages: number }
  | { type: "setNatural"; natural: NaturalSize; rotation: Rotation }
  | { type: "setZoomMode"; mode: ZoomMode }
  | { type: "setZoom"; value: number }
  | { type: "setDerivedZoom"; value: number }
  | { type: "rotatePage"; pageNumber: number }
  | { type: "goto"; page: number }
  | { type: "setCurrentPage"; page: number }
  | { type: "toggleSidebar" }
  | { type: "openSearch" }
  | { type: "closeSearch" }
  | { type: "indexBuilt" }
  | { type: "setSearchQuery"; query: string }
  | { type: "setMatches"; matches: Match[] }
  | { type: "setActiveMatch"; index: number }
  | { type: "nextMatch" }
  | { type: "prevMatch" }
  | { type: "setIndexing"; indexing: PdfState["indexing"] }
  | { type: "openPrint" }
  | { type: "closePrint" }
  | { type: "setLoadError"; error: Error | null }
  | { type: "setPassword"; password: string | null }
  | {
      type: "setPendingPassword";
      pending: PdfState["pendingPassword"];
    }
  | { type: "setProgress"; progress: PdfState["progress"] };

export function pdfReducer(state: PdfState, action: PdfAction): PdfState {
  switch (action.type) {
    case "docLoaded":
      return { ...state, numPages: action.numPages };
    case "setNatural":
      return {
        ...state,
        natural: action.natural,
        naturalRotation: action.rotation,
      };
    case "setZoomMode":
      // The renderer effect derives the actual zoom value from
      // (mode, container, natural) and dispatches setZoom. We only
      // change the mode here; user-typed custom % goes through setZoom.
      return { ...state, zoomMode: action.mode };
    case "setZoom":
      // Manual zoom always flips the mode to "custom" so the next
      // resize doesn't reset the user's value back to fit-width.
      return { ...state, zoom: action.value, zoomMode: "custom" };
    case "setDerivedZoom":
      // Updates the zoom value WITHOUT changing the mode. Used by the
      // orchestrator's effect when it recomputes zoom for a non-custom
      // mode (e.g. fitWidth) after container resize or natural-size load.
      if (state.zoom === action.value) return state;
      return { ...state, zoom: action.value };
    case "rotatePage": {
      const cur = state.rotations[action.pageNumber] ?? 0;
      const next = ((cur + 90) % 360) as Rotation;
      const rotations = { ...state.rotations };
      if (next === 0) {
        // Keep the record sparse; 0 is the default.
        delete rotations[action.pageNumber];
      } else {
        rotations[action.pageNumber] = next;
      }
      return { ...state, rotations };
    }
    case "goto": {
      if (state.numPages == null) return state;
      const clamped = clamp(action.page, 1, state.numPages);
      if (clamped === state.currentPage) return state;
      return { ...state, currentPage: clamped };
    }
    case "setCurrentPage": {
      // Used by the scroll-position observer; clamping isn't needed because
      // the virtualizer's indices are already valid, but we guard anyway.
      if (state.numPages == null) return state;
      const clamped = clamp(action.page, 1, state.numPages);
      if (clamped === state.currentPage) return state;
      return { ...state, currentPage: clamped };
    }
    case "toggleSidebar":
      return { ...state, sidebarOpen: !state.sidebarOpen };
    case "openSearch":
      return {
        ...state,
        search: {
          ...state.search,
          open: true,
          // Always bump openVersion so the panel re-focuses on repeat Cmd-F.
          openVersion: state.search.openVersion + 1,
        },
      };
    case "closeSearch":
      return {
        ...state,
        search: {
          open: false,
          openVersion: state.search.openVersion,
          query: "",
          matches: [],
          activeIndex: -1,
        },
      };
    case "indexBuilt":
      return { ...state, indexVersion: state.indexVersion + 1 };
    case "setSearchQuery":
      // Query change resets activeIndex; the renderer's effect recomputes
      // matches and then dispatches setMatches.
      return {
        ...state,
        search: {
          ...state.search,
          query: action.query,
          matches: [],
          activeIndex: -1,
        },
      };
    case "setMatches":
      return {
        ...state,
        search: {
          ...state.search,
          matches: action.matches,
          activeIndex: action.matches.length > 0 ? 0 : -1,
        },
      };
    case "setActiveMatch": {
      if (state.search.matches.length === 0) return state;
      const idx = clamp(action.index, 0, state.search.matches.length - 1);
      return { ...state, search: { ...state.search, activeIndex: idx } };
    }
    case "nextMatch": {
      const total = state.search.matches.length;
      if (total === 0) return state;
      const next = (state.search.activeIndex + 1) % total;
      return { ...state, search: { ...state.search, activeIndex: next } };
    }
    case "prevMatch": {
      const total = state.search.matches.length;
      if (total === 0) return state;
      const prev = (state.search.activeIndex - 1 + total) % total;
      return { ...state, search: { ...state.search, activeIndex: prev } };
    }
    case "setIndexing":
      return { ...state, indexing: action.indexing };
    case "openPrint":
      return { ...state, printOpen: true };
    case "closePrint":
      return { ...state, printOpen: false };
    case "setLoadError":
      return { ...state, loadError: action.error };
    case "setPassword":
      return { ...state, password: action.password };
    case "setPendingPassword":
      return { ...state, pendingPassword: action.pending };
    case "setProgress":
      return { ...state, progress: action.progress };
  }
}

function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}

/**
 * Derive the on-screen display dimensions of a page given current state and
 * the layout container width. When rotation is 90/270 the natural width and
 * height swap. The zoom cap of the previous implementation is intentionally
 * absent — we want overflow-x so users can scroll a 200% page horizontally.
 */
export function getPageDimensions(
  state: PdfState,
  pageNumber: number,
  _containerWidth: number,
  containerHeight: number,
): { width: number; height: number } {
  if (!state.natural) return { width: 0, height: containerHeight || 800 };
  const rotation = state.rotations[pageNumber] ?? 0;
  const rotated = rotation === 90 || rotation === 270;
  const naturalW = rotated ? state.natural.height : state.natural.width;
  const naturalH = rotated ? state.natural.width : state.natural.height;
  const width = naturalW * state.zoom;
  const height = (width / naturalW) * naturalH;
  return { width, height };
}

/**
 * Compute the zoom value for a non-custom mode given the container.
 * Returns null when we lack the inputs needed (no natural size or
 * container hasn't been measured yet).
 */
export function computeZoomForMode(
  mode: ZoomMode,
  natural: NaturalSize | null,
  containerWidth: number,
  containerHeight: number,
  gutter: number,
): number | null {
  if (!natural || containerWidth <= 0) return null;
  switch (mode) {
    case "fitWidth":
      return (containerWidth - gutter * 2) / natural.width;
    case "fitPage": {
      // Constrain by both axes; pick the smaller scale so the page fits.
      if (containerHeight <= 0) return null;
      const wScale = (containerWidth - gutter * 2) / natural.width;
      const hScale = (containerHeight - gutter * 2) / natural.height;
      return Math.min(wScale, hScale);
    }
    case "actual":
      return 1;
    case "custom":
      // Caller shouldn't ask us — custom is user-driven.
      return null;
  }
}
