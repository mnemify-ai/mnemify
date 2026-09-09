// Absolute-positioned overlay drawing merged cells on top of the virtualized
// base rows. Sits inside the virtualized container (which itself sits below
// the sticky header), so coords here are relative to data-row index 0.
//
// Address convention: ParsedSheet.merges uses display rows (0 = header,
// 1..N = data). When we project, we subtract 1 from row indices to get
// data-row indices that the geometry cache understands. Merges that
// include the header row (s.r === 0) are skipped in v1 — they're rare and
// the sticky header makes geometry brittle.

import type { CSSProperties } from "react";
import { intersectsRowRange, projectMerge, type SheetGeometry } from "./geometry";
import { cellStyleToProps, type ExcelStyle } from "./cellFormatting";
import { cellKey, highlightCellHtml, type Match } from "./searchIndex";
import type { CellView, SheetMerge } from "./useSheetParse";

interface MergeOverlayProps {
  merges: SheetMerge[];
  geometry: SheetGeometry;
  /** Pixel width of the row-number gutter at the left of the grid. */
  rowNumGutterPx: number;
  /** Visible data-row range from the virtualizer (used for cull). */
  visibleDataRowStart: number;
  visibleDataRowEnd: number;
  /** Top-left cell values (display-row indexed: rows[0]=headers, rows[1]=data row 0…). */
  headers: string[];
  rows: CellView[][];
  styles: Map<string, ExcelStyle>;
  /** Active-sheet search highlighting. */
  sheetIndex: number;
  matchesByCell: Map<string, Match[]>;
  activeMatch: Match | null;
}

export function MergeOverlay({
  merges,
  geometry,
  rowNumGutterPx,
  visibleDataRowStart,
  visibleDataRowEnd,
  headers,
  rows,
  styles,
  sheetIndex,
  matchesByCell,
  activeMatch,
}: MergeOverlayProps) {
  if (merges.length === 0) return null;

  return (
    <>
      {merges.map((m, i) => {
        // Skip merges that include the header row — sticky-header geometry
        // is unreliable and these are vanishingly rare in real workbooks.
        if (m.s.r < 1) return null;
        // Translate display rows to data-row indices for the geometry cache.
        const dataStartRow = m.s.r - 1;
        const dataEndRow = m.e.r - 1;
        if (!intersectsRowRange(dataStartRow, dataEndRow, visibleDataRowStart, visibleDataRowEnd))
          return null;

        const rect = projectMerge(geometry, dataStartRow, m.s.c, dataEndRow, m.e.c);

        const text = displayValueFor(m.s.r, m.s.c, headers, rows);
        const style = styles.get(`${m.s.r}:${m.s.c}`);
        const styled = cellStyleToProps(style);
        const inlineMatches = matchesByCell.get(cellKey(sheetIndex, m.s.r, m.s.c));

        const css: CSSProperties = {
          position: "absolute",
          left: rect.left + rowNumGutterPx,
          top: rect.top,
          width: rect.width,
          height: rect.height,
          pointerEvents: "auto",
          ...styled.style,
        };

        return (
          <div
            key={i}
            className={`sheet-merge sheet-cell ${styled.className}`}
            style={css}
            title={text}
            dangerouslySetInnerHTML={{
              __html: highlightCellHtml(text, inlineMatches, activeMatch),
            }}
          />
        );
      })}
    </>
  );
}

function displayValueFor(
  displayRow: number,
  displayCol: number,
  headers: string[],
  rows: CellView[][],
): string {
  if (displayRow === 0) return headers[displayCol] ?? "";
  const row = rows[displayRow - 1];
  return row?.[displayCol]?.value ?? "";
}
