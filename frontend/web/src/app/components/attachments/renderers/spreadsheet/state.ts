// Reducer for the spreadsheet viewer.
//
// Cross-cutting state lives here: active sheet, zoom, search, per-sheet
// overrides (resize / hide / sort / filter). Local UI (which header menu is
// open, current drag delta) stays in the component that owns it.
//
// Per-sheet state is keyed by sheetName (not index) so switching sheets,
// hiding a column, and switching back preserves your changes — and so does
// re-opening the same attachment in the same session via sessionStorage.

import type { Match } from "./searchIndex";

export interface SearchState {
  open: boolean;
  /** Bumped on every openSearch dispatch so SearchPanel can re-focus + select. */
  openVersion: number;
  query: string;
  matches: Match[];
  /** -1 when there are no matches or none active yet. */
  activeIndex: number;
}

export type SortDirection = "asc" | "desc";

export interface SortBy {
  col: number;
  direction: SortDirection;
}

export type Filters = Record<number /* col */, string[]>;

export interface SheetOverrides {
  colWidths: Record<number, number>;
  rowHeights: Record<number, number>;
  hiddenCols: number[];
  hiddenRows: number[];
}

export interface PerSheet {
  overrides: SheetOverrides;
  sortBy: SortBy | null;
  filters: Filters;
}

export interface SheetState {
  activeSheet: number;
  zoom: number;
  search: SearchState;
  indexing: { done: number; total: number } | null;
  /** Bumped on each index-build chunk completion so the match-compute
   *  effect re-runs against the larger index. */
  indexVersion: number;
  /** Per-sheet state, keyed by sheetName. Empty entries default at read. */
  perSheet: Record<string, PerSheet>;
}

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 4;

export function emptyOverrides(): SheetOverrides {
  return { colWidths: {}, rowHeights: {}, hiddenCols: [], hiddenRows: [] };
}

export function emptyPerSheet(): PerSheet {
  return { overrides: emptyOverrides(), sortBy: null, filters: {} };
}

export const initialSheetState: SheetState = {
  activeSheet: 0,
  zoom: 1,
  search: { open: false, openVersion: 0, query: "", matches: [], activeIndex: -1 },
  indexing: null,
  indexVersion: 0,
  perSheet: {},
};

export type SheetAction =
  | { type: "setActiveSheet"; index: number }
  | { type: "setZoom"; value: number }
  | { type: "openSearch" }
  | { type: "closeSearch" }
  | { type: "setSearchQuery"; query: string }
  | { type: "setMatches"; matches: Match[] }
  | { type: "setActiveMatch"; index: number }
  | { type: "nextMatch" }
  | { type: "prevMatch" }
  | { type: "setIndexing"; indexing: SheetState["indexing"] }
  | { type: "indexBuilt" }
  | { type: "resizeColumn"; sheetName: string; col: number; width: number }
  | { type: "resizeRow"; sheetName: string; row: number; height: number }
  | { type: "hideColumn"; sheetName: string; col: number }
  | { type: "hideRow"; sheetName: string; row: number }
  | { type: "showColumn"; sheetName: string; col: number }
  | { type: "showRow"; sheetName: string; row: number }
  | { type: "showAll"; sheetName: string }
  | { type: "setSort"; sheetName: string; sortBy: SortBy | null }
  | { type: "setFilter"; sheetName: string; col: number; values: string[] }
  | { type: "clearFilter"; sheetName: string; col: number }
  | { type: "clearAllFilters"; sheetName: string }
  | { type: "resetOverrides"; sheetName: string }
  | { type: "hydrateOverrides"; perSheet: Record<string, PerSheet> };

export function sheetReducer(state: SheetState, action: SheetAction): SheetState {
  switch (action.type) {
    case "setActiveSheet":
      if (state.activeSheet === action.index) return state;
      return { ...state, activeSheet: action.index };

    case "setZoom": {
      const clamped = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, action.value));
      if (clamped === state.zoom) return state;
      return { ...state, zoom: clamped };
    }

    case "openSearch":
      return {
        ...state,
        search: {
          ...state.search,
          open: true,
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

    case "setSearchQuery":
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
      const idx = Math.max(
        0,
        Math.min(state.search.matches.length - 1, action.index),
      );
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

    case "indexBuilt":
      return { ...state, indexVersion: state.indexVersion + 1 };

    case "resizeColumn":
      return mutateOverrides(state, action.sheetName, (o) => ({
        ...o,
        colWidths: { ...o.colWidths, [action.col]: action.width },
      }));

    case "resizeRow":
      return mutateOverrides(state, action.sheetName, (o) => ({
        ...o,
        rowHeights: { ...o.rowHeights, [action.row]: action.height },
      }));

    case "hideColumn":
      return mutateOverrides(state, action.sheetName, (o) =>
        o.hiddenCols.includes(action.col)
          ? o
          : { ...o, hiddenCols: [...o.hiddenCols, action.col].sort((a, b) => a - b) },
      );

    case "hideRow":
      return mutateOverrides(state, action.sheetName, (o) =>
        o.hiddenRows.includes(action.row)
          ? o
          : { ...o, hiddenRows: [...o.hiddenRows, action.row].sort((a, b) => a - b) },
      );

    case "showColumn":
      return mutateOverrides(state, action.sheetName, (o) => ({
        ...o,
        hiddenCols: o.hiddenCols.filter((c) => c !== action.col),
      }));

    case "showRow":
      return mutateOverrides(state, action.sheetName, (o) => ({
        ...o,
        hiddenRows: o.hiddenRows.filter((r) => r !== action.row),
      }));

    case "showAll":
      return mutateOverrides(state, action.sheetName, (o) => ({
        ...o,
        hiddenCols: [],
        hiddenRows: [],
      }));

    case "setSort":
      return mutatePerSheet(state, action.sheetName, (ps) => ({
        ...ps,
        sortBy: action.sortBy,
      }));

    case "setFilter":
      return mutatePerSheet(state, action.sheetName, (ps) => ({
        ...ps,
        filters: { ...ps.filters, [action.col]: action.values },
      }));

    case "clearFilter":
      return mutatePerSheet(state, action.sheetName, (ps) => {
        const { [action.col]: _drop, ...rest } = ps.filters;
        return { ...ps, filters: rest };
      });

    case "clearAllFilters":
      return mutatePerSheet(state, action.sheetName, (ps) => ({
        ...ps,
        filters: {},
      }));

    case "resetOverrides":
      return mutatePerSheet(state, action.sheetName, () => emptyPerSheet());

    case "hydrateOverrides":
      // Used at mount to restore from sessionStorage.
      return { ...state, perSheet: action.perSheet };
  }
}

function mutateOverrides(
  state: SheetState,
  sheetName: string,
  fn: (o: SheetOverrides) => SheetOverrides,
): SheetState {
  return mutatePerSheet(state, sheetName, (ps) => ({
    ...ps,
    overrides: fn(ps.overrides),
  }));
}

function mutatePerSheet(
  state: SheetState,
  sheetName: string,
  fn: (ps: PerSheet) => PerSheet,
): SheetState {
  const cur = state.perSheet[sheetName] ?? emptyPerSheet();
  return {
    ...state,
    perSheet: { ...state.perSheet, [sheetName]: fn(cur) },
  };
}

/** Stable shared singleton for the "no overrides yet" case. Returning a
 *  fresh emptyPerSheet() each call would invalidate every downstream useMemo
 *  on every parent render. Frozen to catch accidental mutation. */
const SHARED_EMPTY_PER_SHEET: PerSheet = Object.freeze({
  overrides: Object.freeze({
    colWidths: Object.freeze({}) as Record<number, number>,
    rowHeights: Object.freeze({}) as Record<number, number>,
    hiddenCols: Object.freeze([]) as unknown as number[],
    hiddenRows: Object.freeze([]) as unknown as number[],
  }) as SheetOverrides,
  sortBy: null,
  filters: Object.freeze({}) as Filters,
}) as PerSheet;

/** Read-only accessor that returns a stable empty value for missing keys
 *  so render code can call `getPerSheet(state, name).filters` unconditionally
 *  without invalidating downstream useMemos. */
export function getPerSheet(state: SheetState, sheetName: string): PerSheet {
  return state.perSheet[sheetName] ?? SHARED_EMPTY_PER_SHEET;
}

/** Sort + filter active? Used to decide whether to hide the merge/image
 *  overlay (which would be wrong over a reordered grid). */
export function isViewReordered(perSheet: PerSheet): boolean {
  if (perSheet.sortBy !== null) return true;
  return Object.values(perSheet.filters).some((vs) => vs.length > 0);
}
