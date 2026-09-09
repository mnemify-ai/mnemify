// XLSX/XLS/CSV preview renderer.
//
// Architecture:
//   * SheetJS parses on first paint (sync); ExcelJS layers in images +
//     merges + cell styles for .xlsx files via a dynamic-import sidecar.
//     See `useSheetParse.ts` for the dual-parse details.
//   * Base layer: virtualized rows in a flex grid (header sticky, row-num
//     gutter sticky).
//   * Overlay layers: absolute-positioned MergeOverlay + ImageOverlay sit
//     above the virtualized rows. Hidden whenever sort or filter is active
//     because the row order is reshuffled and merges/images reference
//     fixed sheet coordinates.
//   * Toolbar (top): search, hide menu, zoom, reset. Sheet tabs stay in
//     the modal footer via the existing `chrome.sheets` contract.
//
// Search uses cell-level matches that auto-switch sheets and scroll to the
// matching cell with magenta highlight (same pattern as the PDF cycle).
// Right-click on a header opens HeaderContextMenu (hide / sort / filter).

import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, Filter } from "lucide-react";
import { ErrorState } from "../../../ui/ErrorState";
import { Skeleton } from "../../../ui/Skeleton";
import { EmptyState } from "../../../ui/EmptyState";
import { cn } from "../../../../lib/cn";
import "../../../../theme/sheet.css";
import type { RendererProps } from "../../registry";
import {
  buildIndexChunked,
  cellKey,
  findMatches,
  groupMatchesByCell,
  highlightCellHtml,
  type Match,
  type SheetSearchIndex,
} from "./searchIndex";
import {
  emptyPerSheet,
  getPerSheet,
  initialSheetState,
  isViewReordered,
  sheetReducer,
  type SortDirection,
} from "./state";
import { buildGeometry, effectiveColWidths } from "./geometry";
import { useSheetParse, type CellView, type ParsedSheet } from "./useSheetParse";
import { cellStyleToProps, type ExcelStyle } from "./cellFormatting";
import { SpreadsheetToolbar } from "./SpreadsheetToolbar";
import { MergeOverlay } from "./MergeOverlay";
import { ImageOverlay } from "./ImageOverlay";
import {
  HeaderContextMenu,
  type ContextMenuTarget,
} from "./HeaderContextMenu";
import { FilterMenu } from "./FilterMenu";
import { columnLabel } from "./HideMenu";

const ROW_HEIGHT = 32;
const HEADER_HEIGHT = 36;
const COL_LABEL_HEIGHT = 22;
const ROWNUM_GUTTER = 56;
const MIN_COL_PX = 32;
const MAX_COL_PX = 800;

interface FilterMenuTarget {
  col: number;
  x: number;
  y: number;
}

export default function SpreadsheetRenderer({
  inlineUrl,
  onChrome,
  attachment,
}: RendererProps) {
  const parse = useSheetParse(inlineUrl, attachment.name);
  const [state, dispatch] = useReducer(sheetReducer, initialSheetState);

  // SessionStorage persistence for overrides (per-attachment scope).
  const persistKey = `mnemify:sheet-overrides:${attachment.url}`;
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(persistKey);
      if (raw) {
        const perSheet = JSON.parse(raw);
        if (perSheet && typeof perSheet === "object") {
          dispatch({ type: "hydrateOverrides", perSheet });
        }
      }
    } catch {
      // sessionStorage may be disabled (incognito + restrictive); not fatal.
    }
    // Only hydrate once on mount per attachment.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [persistKey]);

  useEffect(() => {
    try {
      sessionStorage.setItem(persistKey, JSON.stringify(state.perSheet));
    } catch {
      // Out of quota / disabled; safe to skip.
    }
  }, [state.perSheet, persistKey]);

  const sheets = parse.workbook?.sheets ?? [];
  const sheetNames = useMemo(() => sheets.map((s) => s.name), [sheets]);
  const activeSheetIndex = Math.min(state.activeSheet, sheetNames.length - 1);
  const activeSheet: ParsedSheet | undefined = sheets[activeSheetIndex];

  // Per-sheet derived state — overrides + sort + filter for the active sheet.
  const perSheet = activeSheet
    ? getPerSheet(state, activeSheet.name)
    : emptyPerSheet();

  // Display row order: identity unless sort or filter is active.
  const displayRowOrder = useMemo(() => {
    if (!activeSheet) return [] as number[];
    return computeDisplayOrder(activeSheet, perSheet);
  }, [activeSheet, perSheet]);

  const reordered = isViewReordered(perSheet);

  // Effective widths/heights honoring overrides, hidden state, zoom.
  const hiddenCols = useMemo(
    () => new Set(perSheet.overrides.hiddenCols),
    [perSheet.overrides.hiddenCols],
  );
  const hiddenRows = useMemo(
    () => new Set(perSheet.overrides.hiddenRows),
    [perSheet.overrides.hiddenRows],
  );
  const colWidths = useMemo(() => {
    if (!activeSheet) return [];
    return effectiveColWidths({
      baseWidths: activeSheet.baseColWidths,
      overrides: perSheet.overrides.colWidths,
      hidden: hiddenCols,
      zoom: state.zoom,
    });
  }, [activeSheet, perSheet.overrides.colWidths, hiddenCols, state.zoom]);

  // Row heights are positional; when displayRowOrder reorders things, we
  // build heights in the new order so the geometry rowTops matches.
  const rowHeights = useMemo(() => {
    if (!activeSheet) return [];
    const baseHeights = activeSheet.baseRowHeights;
    const overrides = perSheet.overrides.rowHeights;
    const out = new Array<number>(displayRowOrder.length);
    for (let i = 0; i < displayRowOrder.length; i++) {
      const realRow = displayRowOrder[i];
      // Hidden data row in original-order? Skip via 0 height.
      if (hiddenRows.has(realRow + 1)) {
        out[i] = 0;
        continue;
      }
      const baseH = baseHeights[realRow] ?? ROW_HEIGHT;
      const override = overrides[realRow + 1]; // hidden/rowHeight indexed by display row
      out[i] = (override ?? baseH) * state.zoom;
    }
    return out;
  }, [
    activeSheet,
    displayRowOrder,
    perSheet.overrides.rowHeights,
    hiddenRows,
    state.zoom,
  ]);

  // Pre-zoom row heights (without the multiplier) for the geometry function.
  // effectiveRowHeights already applies zoom; we built it manually above.
  const geometry = useMemo(
    () => buildGeometry(colWidths, rowHeights),
    [colWidths, rowHeights],
  );

  const totalContentWidth = geometry.colLefts.at(-1) ?? 0;

  // Virtualizer drives just the data rows (header is sticky outside it).
  const scrollRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: displayRowOrder.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i: number) => rowHeights[i] ?? ROW_HEIGHT,
    overscan: 10,
  });

  useEffect(() => {
    rowVirtualizer.measure();
  }, [rowHeights, rowVirtualizer]);

  const virtualItems = rowVirtualizer.getVirtualItems();
  const visibleStart = virtualItems[0]?.index ?? 0;
  const visibleEnd = virtualItems.at(-1)?.index ?? 0;

  // Report sheet tabs + onFind to modal footer.
  const openSearch = useCallback(() => dispatch({ type: "openSearch" }), []);
  useEffect(() => {
    onChrome({
      sheets:
        sheetNames.length > 1
          ? {
              names: sheetNames,
              active: activeSheetIndex,
              select: (i) => dispatch({ type: "setActiveSheet", index: i }),
            }
          : undefined,
      onFind: openSearch,
    });
  }, [sheetNames, activeSheetIndex, openSearch, onChrome]);

  // Reset active sheet when workbook changes.
  useEffect(() => {
    dispatch({ type: "setActiveSheet", index: 0 });
  }, [parse.workbook]);

  // ----- Search ---------------------------------------------------------
  const indexRef = useRef<SheetSearchIndex>([]);
  const indexAbortRef = useRef<AbortController | null>(null);

  // Lazy-build index on first openSearch (or on workbook change after open).
  useEffect(() => {
    if (!state.search.open || sheets.length === 0) return;
    indexAbortRef.current?.abort();
    const controller = new AbortController();
    indexAbortRef.current = controller;
    const sources = sheets.map((s, i) => ({
      sheetIndex: i,
      sheetName: s.name,
      headers: s.headers,
      rows: s.rows,
    }));
    const totalCells = sources.reduce(
      (n, s) => n + s.headers.length + s.rows.reduce((m, r) => m + r.length, 0),
      0,
    );
    dispatch({
      type: "setIndexing",
      indexing: { done: 0, total: totalCells },
    });
    let done = 0;
    buildIndexChunked(
      sources,
      (partial) => {
        indexRef.current = partial;
        done = partial.reduce((n, s) => n + (s?.cells.length ?? 0), 0);
        dispatch({ type: "setIndexing", indexing: { done, total: totalCells } });
        dispatch({ type: "indexBuilt" });
      },
      controller.signal,
    )
      .then((full) => {
        indexRef.current = full;
        dispatch({ type: "setIndexing", indexing: null });
        dispatch({ type: "indexBuilt" });
      })
      .catch(() => {
        // Aborted on unmount or re-open; no action needed.
      });

    return () => controller.abort();
  }, [state.search.open, sheets]);

  // Recompute matches when query or index changes.
  useEffect(() => {
    if (!state.search.query) {
      dispatch({ type: "setMatches", matches: [] });
      return;
    }
    if (indexRef.current.length === 0) return;
    const matches = findMatches(indexRef.current, state.search.query);
    dispatch({ type: "setMatches", matches });
  }, [state.search.query, state.indexVersion]);

  const activeMatch =
    state.search.activeIndex >= 0
      ? state.search.matches[state.search.activeIndex] ?? null
      : null;

  const matchesByCell = useMemo(
    () => groupMatchesByCell(state.search.matches),
    [state.search.matches],
  );

  // When the active match is in the current sheet but its row got filtered
  // or hidden out, the user would see no visual change on Next — surface it
  // explicitly in the search status (handled in SpreadsheetSearchPanel).
  const activeMatchHidden = useMemo(() => {
    if (!activeMatch || activeMatch.sheetIndex !== activeSheetIndex) return false;
    if (activeMatch.row === 0) return false; // header always visible
    const realRow = activeMatch.row - 1;
    if (hiddenRows.has(activeMatch.row)) return true;
    if (hiddenCols.has(activeMatch.col)) return true;
    return displayRowOrder.indexOf(realRow) < 0;
  }, [activeMatch, activeSheetIndex, displayRowOrder, hiddenRows, hiddenCols]);

  // Scroll to active match: switch sheet if needed, then scroll to row + col.
  // Crucial: when the match is in a different sheet, dispatch + return; this
  // effect re-runs on the next render with the *new* sheet's closure
  // (displayRowOrder, geometry). Scrolling in the same render would use the
  // OLD sheet's order and either no-op or land on the wrong cell.
  useEffect(() => {
    if (!activeMatch) return;
    if (activeMatch.sheetIndex !== activeSheetIndex) {
      dispatch({ type: "setActiveSheet", index: activeMatch.sheetIndex });
      return;
    }
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        scrollToMatch(activeMatch);
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMatch, activeSheetIndex]);

  function scrollToMatch(match: Match) {
    const scroller = scrollRef.current;
    if (!scroller) return;
    // Convert display row (0 = header, 1..N = data rows) to position in
    // the current displayRowOrder.
    if (match.row === 0) {
      scroller.scrollTo({ top: 0, behavior: "smooth" });
    } else {
      const realRow = match.row - 1;
      const pos = displayRowOrder.indexOf(realRow);
      if (pos >= 0) {
        rowVirtualizer.scrollToIndex(pos, { align: "center" });
      }
    }
    // Horizontal scroll so the column is visible.
    const cellLeft = geometry.colLefts[match.col] ?? 0;
    scroller.scrollTo({
      left: cellLeft + ROWNUM_GUTTER - 64,
      behavior: "smooth",
    });
  }

  // ----- Resize drag ----------------------------------------------------
  const dragRef = useRef<{
    col: number;
    startX: number;
    startWidth: number;
  } | null>(null);
  const [dragPreviewX, setDragPreviewX] = useState<number | null>(null);

  function onColResizeStart(col: number, startWidth: number) {
    return (e: ReactMouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragRef.current = { col, startX: e.clientX, startWidth };
      setDragPreviewX(e.clientX);
      window.addEventListener("mousemove", onResizeMove);
      window.addEventListener("mouseup", onResizeEnd);
    };
  }

  function onResizeMove(e: globalThis.MouseEvent) {
    if (!dragRef.current) return;
    setDragPreviewX(e.clientX);
  }

  function onResizeEnd(e: globalThis.MouseEvent) {
    window.removeEventListener("mousemove", onResizeMove);
    window.removeEventListener("mouseup", onResizeEnd);
    setDragPreviewX(null);
    if (!dragRef.current || !activeSheet) return;
    const { col, startX, startWidth } = dragRef.current;
    dragRef.current = null;
    const delta = e.clientX - startX;
    const next = Math.max(MIN_COL_PX, Math.min(MAX_COL_PX, startWidth + delta));
    dispatch({
      type: "resizeColumn",
      sheetName: activeSheet.name,
      col,
      width: next / state.zoom, // store at zoom 1
    });
  }

  // ----- Header context menu --------------------------------------------
  const [contextMenu, setContextMenu] = useState<ContextMenuTarget | null>(null);
  const [filterMenu, setFilterMenu] = useState<FilterMenuTarget | null>(null);

  function openContextMenuForCol(col: number, e: ReactMouseEvent) {
    e.preventDefault();
    setContextMenu({ kind: "col", index: col, x: e.clientX, y: e.clientY });
  }

  function openContextMenuForRow(displayRow: number, e: ReactMouseEvent) {
    e.preventDefault();
    setContextMenu({ kind: "row", index: displayRow, x: e.clientX, y: e.clientY });
  }

  function openFilterMenu(col: number, x: number, y: number) {
    setFilterMenu({ col, x, y });
  }

  // ----- Sort + filter handlers -----------------------------------------
  const sheetName = activeSheet?.name ?? "";

  function cycleSort(col: number, dir: SortDirection) {
    if (!activeSheet) return;
    const current = perSheet.sortBy;
    if (current?.col === col && current.direction === dir) {
      dispatch({ type: "setSort", sheetName, sortBy: null });
    } else {
      dispatch({ type: "setSort", sheetName, sortBy: { col, direction: dir } });
    }
  }

  // ----- Loading / error states -----------------------------------------
  if (parse.status === "loading") {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center p-8" aria-busy>
        <div className="w-full max-w-3xl space-y-2">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} variant="line" width={i === 5 ? "80%" : "100%"} />
          ))}
        </div>
      </div>
    );
  }
  if (parse.status === "error" || !parse.workbook) {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center p-6">
        <ErrorState
          title="Couldn't load file"
          description={
            parse.error?.message ?? `${attachment.name} couldn't be opened.`
          }
          onRetry={parse.refetch}
        />
      </div>
    );
  }
  if (!activeSheet || activeSheet.headers.length === 0) {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center p-6">
        <EmptyState title="Empty sheet" description="This sheet contains no cells." />
      </div>
    );
  }

  const hasOverrides =
    perSheet.overrides.hiddenCols.length > 0 ||
    perSheet.overrides.hiddenRows.length > 0 ||
    Object.keys(perSheet.overrides.colWidths).length > 0 ||
    Object.keys(perSheet.overrides.rowHeights).length > 0 ||
    perSheet.sortBy !== null ||
    Object.values(perSheet.filters).some((vs) => vs.length > 0);

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <SpreadsheetToolbar
        searchOpen={state.search.open}
        searchOpenVersion={state.search.openVersion}
        searchQuery={state.search.query}
        matches={state.search.matches}
        activeMatchIndex={state.search.activeIndex}
        activeMatchHidden={activeMatchHidden}
        sheetNames={sheetNames}
        indexing={state.indexing}
        hiddenCols={perSheet.overrides.hiddenCols}
        hiddenRows={perSheet.overrides.hiddenRows}
        zoom={state.zoom}
        hasOverrides={hasOverrides}
        onOpenSearch={openSearch}
        onCloseSearch={() => dispatch({ type: "closeSearch" })}
        onSearchQueryChange={(q) =>
          dispatch({ type: "setSearchQuery", query: q })
        }
        onNextMatch={() => dispatch({ type: "nextMatch" })}
        onPrevMatch={() => dispatch({ type: "prevMatch" })}
        onShowCol={(col) =>
          dispatch({ type: "showColumn", sheetName, col })
        }
        onShowRow={(row) => dispatch({ type: "showRow", sheetName, row })}
        onShowAll={() => dispatch({ type: "showAll", sheetName })}
        onZoomChange={(z) => dispatch({ type: "setZoom", value: z })}
        onResetOverrides={() =>
          dispatch({ type: "resetOverrides", sheetName })
        }
      />

      {reordered && (activeSheet.merges.length > 0 || activeSheet.images.length > 0) && (
        <div
          role="status"
          className="px-3 py-1.5 text-[11px] font-sans text-ink bg-bone/60 border-b border-hair"
        >
          Merged cells and images are hidden while sort or filter is active.{" "}
          <button
            type="button"
            onClick={() => dispatch({ type: "resetOverrides", sheetName })}
            className="text-magenta hover:underline"
          >
            Reset
          </button>{" "}
          to view them.
        </div>
      )}

      <div
        ref={scrollRef}
        className="flex-1 min-h-0 overflow-auto"
        tabIndex={0}
        aria-label={`Spreadsheet ${activeSheet.name}`}
      >
        <div
          className="sheet-grid"
          style={{
            minWidth: totalContentWidth + ROWNUM_GUTTER,
            fontSize: `${12 * state.zoom}px`,
          }}
        >
          {/* Excel-style column letter bar (A, B, C…). Sticky at the very top,
              above the data-header row, with the column-resize handle. */}
          <div
            className="sheet-row sheet-collabel-row"
            style={{ height: COL_LABEL_HEIGHT * state.zoom, top: 0 }}
          >
            <div
              className="sheet-rownum sheet-collabel-corner"
              style={{ width: ROWNUM_GUTTER }}
              aria-hidden
            >
              &nbsp;
            </div>
            {activeSheet.headers.map((_h, c) => {
              if (hiddenCols.has(c)) return null;
              return (
                <div
                  key={c}
                  className="sheet-cell sheet-collabel-cell"
                  style={{ width: colWidths[c], position: "relative" }}
                  onContextMenu={(e) => openContextMenuForCol(c, e)}
                  aria-label={`Column ${columnLabel(c)}`}
                >
                  <span className="sheet-collabel-letter">{columnLabel(c)}</span>
                  <span
                    className="sheet-resize-handle"
                    onMouseDown={onColResizeStart(c, colWidths[c])}
                    aria-hidden
                  />
                </div>
              );
            })}
          </div>

          {/* Sticky header — row 1 of the workbook, with hover-revealed sort
              and filter affordances. Plain click does NOT auto-sort. */}
          <div
            className="sheet-row sheet-header"
            style={{
              height: HEADER_HEIGHT * state.zoom,
              top: COL_LABEL_HEIGHT * state.zoom,
            }}
          >
            <div
              className="sheet-rownum"
              style={{ width: ROWNUM_GUTTER }}
              aria-hidden
            >
              &nbsp;
            </div>
            {activeSheet.headers.map((h, c) => {
              if (hiddenCols.has(c)) return null;
              const sb = perSheet.sortBy;
              const sortedDir = sb?.col === c ? sb.direction : null;
              const hasFilter = (perSheet.filters[c]?.length ?? 0) > 0;
              return (
                <div
                  key={c}
                  className="sheet-cell sheet-header-cell"
                  style={{ width: colWidths[c], position: "relative" }}
                  title={h}
                  onContextMenu={(e) => openContextMenuForCol(c, e)}
                >
                  <span className="truncate sheet-header-text">
                    {h || <span className="sheet-cell-empty">—</span>}
                  </span>
                  <div className="sheet-header-actions">
                    <button
                      type="button"
                      aria-label={`Sort ${columnLabel(c)} ascending`}
                      onClick={(e) => {
                        e.stopPropagation();
                        cycleSort(c, "asc");
                      }}
                      className={cn(
                        "sheet-action-icon",
                        sortedDir === "asc" && "sheet-action-icon-active",
                      )}
                    >
                      <ArrowUp size={11} strokeWidth={2} aria-hidden />
                    </button>
                    <button
                      type="button"
                      aria-label={`Sort ${columnLabel(c)} descending`}
                      onClick={(e) => {
                        e.stopPropagation();
                        cycleSort(c, "desc");
                      }}
                      className={cn(
                        "sheet-action-icon",
                        sortedDir === "desc" && "sheet-action-icon-active",
                      )}
                    >
                      <ArrowDown size={11} strokeWidth={2} aria-hidden />
                    </button>
                    <button
                      type="button"
                      aria-label={`Filter ${columnLabel(c)}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        const r = (
                          e.currentTarget as HTMLButtonElement
                        ).getBoundingClientRect();
                        openFilterMenu(c, r.left, r.bottom + 4);
                      }}
                      className={cn(
                        "sheet-action-icon",
                        hasFilter && "sheet-action-icon-active",
                      )}
                    >
                      <Filter size={11} strokeWidth={1.75} aria-hidden />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Virtualized body */}
          <div
            style={{
              height: rowVirtualizer.getTotalSize(),
              position: "relative",
            }}
          >
            {virtualItems.map((vRow) => {
              const realRow = displayRowOrder[vRow.index];
              const row = activeSheet.rows[realRow];
              const displayRow = realRow + 1; // header is row 0
              if (!row) return null;
              return (
                <div
                  key={vRow.key}
                  data-display-row={displayRow}
                  className="sheet-row"
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    right: 0,
                    height: rowHeights[vRow.index],
                    transform: `translateY(${vRow.start}px)`,
                    display: "flex",
                  }}
                >
                  <div
                    className="sheet-rownum"
                    style={{ width: ROWNUM_GUTTER }}
                    onContextMenu={(e) => openContextMenuForRow(displayRow, e)}
                  >
                    {displayRow + 1}
                  </div>
                  {row.map((cell, c) =>
                    hiddenCols.has(c) ? null : (
                      <BodyCell
                        key={c}
                        cell={cell}
                        col={c}
                        width={colWidths[c]}
                        style={activeSheet.styles.get(`${displayRow}:${c}`)}
                        sheetIndex={activeSheetIndex}
                        displayRow={displayRow}
                        matches={matchesByCell.get(
                          cellKey(activeSheetIndex, displayRow, c),
                        )}
                        activeMatch={activeMatch}
                      />
                    ),
                  )}
                </div>
              );
            })}

            {/* Overlay layers — hidden when sort/filter active. */}
            {!reordered && parse.workbook.extended && (
              <>
                <MergeOverlay
                  merges={activeSheet.merges}
                  geometry={geometry}
                  rowNumGutterPx={ROWNUM_GUTTER}
                  visibleDataRowStart={visibleStart}
                  visibleDataRowEnd={visibleEnd}
                  headers={activeSheet.headers}
                  rows={activeSheet.rows}
                  styles={activeSheet.styles}
                  sheetIndex={activeSheetIndex}
                  matchesByCell={matchesByCell}
                  activeMatch={activeMatch}
                />
                <ImageOverlay
                  images={activeSheet.images}
                  geometry={geometry}
                  rowNumGutterPx={ROWNUM_GUTTER}
                  visibleDataRowStart={visibleStart}
                  visibleDataRowEnd={visibleEnd}
                  zoom={state.zoom}
                />
              </>
            )}
          </div>

          {/* Resize guide line. */}
          {dragPreviewX !== null && (
            <div
              className="sheet-resize-guide"
              style={{
                position: "fixed",
                top: 0,
                bottom: 0,
                left: dragPreviewX,
                width: 1,
                pointerEvents: "none",
              }}
              aria-hidden
            />
          )}
        </div>
      </div>

      {contextMenu && (
        <HeaderContextMenu
          target={contextMenu}
          onClose={() => setContextMenu(null)}
          onHide={() => {
            if (!activeSheet) return;
            if (contextMenu.kind === "col") {
              dispatch({
                type: "hideColumn",
                sheetName,
                col: contextMenu.index,
              });
            } else {
              dispatch({
                type: "hideRow",
                sheetName,
                row: contextMenu.index,
              });
            }
          }}
          onSortAsc={
            contextMenu.kind === "col"
              ? () => cycleSort(contextMenu.index, "asc")
              : undefined
          }
          onSortDesc={
            contextMenu.kind === "col"
              ? () => cycleSort(contextMenu.index, "desc")
              : undefined
          }
          onClearSort={
            contextMenu.kind === "col" && perSheet.sortBy?.col === contextMenu.index
              ? () => dispatch({ type: "setSort", sheetName, sortBy: null })
              : undefined
          }
          isSorted={
            contextMenu.kind === "col" && perSheet.sortBy?.col === contextMenu.index
              ? perSheet.sortBy.direction
              : null
          }
          onOpenFilter={
            contextMenu.kind === "col"
              ? () =>
                  openFilterMenu(contextMenu.index, contextMenu.x, contextMenu.y)
              : undefined
          }
          hasFilter={
            contextMenu.kind === "col" &&
            (perSheet.filters[contextMenu.index]?.length ?? 0) > 0
          }
          onClearFilter={
            contextMenu.kind === "col" &&
            (perSheet.filters[contextMenu.index]?.length ?? 0) > 0
              ? () =>
                  dispatch({
                    type: "clearFilter",
                    sheetName,
                    col: contextMenu.index,
                  })
              : undefined
          }
        />
      )}

      {filterMenu && activeSheet && (
        <FilterMenu
          col={filterMenu.col}
          x={filterMenu.x}
          y={filterMenu.y}
          allValues={activeSheet.rows.map((r) => r[filterMenu.col]?.value ?? "")}
          selected={perSheet.filters[filterMenu.col] ?? []}
          onApply={(values) =>
            dispatch({
              type: "setFilter",
              sheetName,
              col: filterMenu.col,
              values,
            })
          }
          onClear={() =>
            dispatch({
              type: "clearFilter",
              sheetName,
              col: filterMenu.col,
            })
          }
          onClose={() => setFilterMenu(null)}
        />
      )}

      {/* Loading hint while ExcelJS enrichment is in flight. */}
      {parse.extending && (
        <div
          className="absolute bottom-3 right-3 px-2.5 py-1 rounded-full bg-cream border border-hair text-[11px] font-mono text-muted shadow"
          role="status"
        >
          Loading rich formatting…
        </div>
      )}
    </div>
  );
}

function computeDisplayOrder(
  sheet: ParsedSheet,
  perSheet: ReturnType<typeof getPerSheet>,
): number[] {
  const n = sheet.rows.length;
  let indices = Array.from({ length: n }, (_, i) => i);

  // Filters (each col → list of allowed values; missing = no filter on that col)
  const activeFilters = Object.entries(perSheet.filters)
    .filter(([, vs]) => vs.length > 0)
    .map(([colStr, vs]) => ({ col: Number(colStr), set: new Set(vs) }));
  if (activeFilters.length > 0) {
    indices = indices.filter((i) =>
      activeFilters.every((f) => f.set.has(sheet.rows[i][f.col]?.value ?? "")),
    );
  }

  // Sort
  if (perSheet.sortBy) {
    const { col, direction } = perSheet.sortBy;
    const dir = direction === "asc" ? 1 : -1;
    indices.sort((a, b) => {
      const va = sheet.rows[a][col];
      const vb = sheet.rows[b][col];
      return compareCells(va, vb) * dir;
    });
  }

  return indices;
}

function compareCells(
  a: CellView | undefined,
  b: CellView | undefined,
): number {
  const av = a?.value ?? "";
  const bv = b?.value ?? "";
  // Numeric-aware sort when both cells are numeric.
  if (a?.numeric && b?.numeric) {
    return parseFloat(av) - parseFloat(bv);
  }
  return av.localeCompare(bv, undefined, { numeric: true, sensitivity: "base" });
}

interface BodyCellProps {
  cell: CellView;
  col: number;
  width: number;
  style?: ExcelStyle;
  sheetIndex: number;
  displayRow: number;
  matches?: Match[];
  activeMatch: Match | null;
}

function BodyCell(props: BodyCellProps) {
  const { cell, width, style, matches, activeMatch } = props;
  const styled = cellStyleToProps(style);
  const numericClass =
    !styled.className.includes("text-") && cell.numeric ? "sheet-cell-numeric" : "";
  const empty = !cell.value;
  return (
    <div
      className={cn("sheet-cell", numericClass, styled.className)}
      style={{ width, ...styled.style }}
      title={cell.value}
    >
      {empty ? (
        <span className="sheet-cell-empty">—</span>
      ) : matches && matches.length > 0 ? (
        <span
          dangerouslySetInnerHTML={{
            __html: highlightCellHtml(cell.value, matches, activeMatch),
          }}
        />
      ) : (
        cell.value
      )}
    </div>
  );
}
