// Geometry caches for the virtualized spreadsheet.
//
// The renderer composes three layers (base virtualized rows, merge overlay,
// image overlay) that all need to agree on where every row/column lives in
// pixel space. Storing one set of cumulative caches here means we compute
// the prefix sums once per resize/hide and every consumer reads from the
// same source.
//
// Hidden columns/rows are represented as `width = 0` rather than spliced
// out of the array, so cell-coordinate ↔ array-index mapping (used by
// search, merges, images) stays trivially correct.

/** 9525 EMU = 1 CSS px at 96 DPI. ExcelJS image anchor offsets are in EMU. */
export const EMU_PER_PX = 9525;

export interface SheetGeometry {
  /** colLefts[c] = sum of widths for columns [0..c-1]. Length = cols+1. */
  colLefts: number[];
  /** rowTops[r] = sum of heights for rows [0..r-1]. Length = rows+1. */
  rowTops: number[];
}

/** Build cumulative caches. Pure — call any time widths/heights change. */
export function buildGeometry(
  colWidths: number[],
  rowHeights: number[],
): SheetGeometry {
  const colLefts = new Array<number>(colWidths.length + 1);
  colLefts[0] = 0;
  for (let i = 0; i < colWidths.length; i++) {
    colLefts[i + 1] = colLefts[i] + colWidths[i];
  }
  const rowTops = new Array<number>(rowHeights.length + 1);
  rowTops[0] = 0;
  for (let i = 0; i < rowHeights.length; i++) {
    rowTops[i + 1] = rowTops[i] + rowHeights[i];
  }
  return { colLefts, rowTops };
}

/**
 * Build the column-widths array honoring overrides + hidden set + zoom.
 * Hidden columns get width 0; user-overridden columns get the override;
 * everything else uses the base (sample-estimated) width. Zoom multiplies
 * the result.
 */
export function effectiveColWidths(params: {
  baseWidths: number[];
  overrides: Record<number, number>;
  hidden: ReadonlySet<number>;
  zoom: number;
}): number[] {
  const { baseWidths, overrides, hidden, zoom } = params;
  const out = new Array<number>(baseWidths.length);
  for (let i = 0; i < baseWidths.length; i++) {
    if (hidden.has(i)) {
      out[i] = 0;
    } else {
      const w = overrides[i] ?? baseWidths[i];
      out[i] = w * zoom;
    }
  }
  return out;
}

/** Symmetric to effectiveColWidths for rows. */
export function effectiveRowHeights(params: {
  baseHeights: number[];
  overrides: Record<number, number>;
  hidden: ReadonlySet<number>;
  zoom: number;
}): number[] {
  const { baseHeights, overrides, hidden, zoom } = params;
  const out = new Array<number>(baseHeights.length);
  for (let i = 0; i < baseHeights.length; i++) {
    if (hidden.has(i)) {
      out[i] = 0;
    } else {
      const h = overrides[i] ?? baseHeights[i];
      out[i] = h * zoom;
    }
  }
  return out;
}

export interface MergeRect {
  /** Pixel coordinates relative to the start of the content area. Add
   *  ROWNUM_GUTTER and HEADER_HEIGHT at the render site, not here. */
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Project a merge `{s:{r,c}, e:{r:r2,c:c2}}` onto pixel coordinates. */
export function projectMerge(
  geometry: SheetGeometry,
  startRow: number,
  startCol: number,
  endRow: number,
  endCol: number,
): MergeRect {
  const left = geometry.colLefts[startCol];
  const top = geometry.rowTops[startRow];
  const width = geometry.colLefts[endCol + 1] - left;
  const height = geometry.rowTops[endRow + 1] - top;
  return { left, top, width, height };
}

/** Convert an EMU offset to CSS pixels. ExcelJS anchor offsets use EMU. */
export function emuToPx(emu: number | undefined | null): number {
  if (!emu) return 0;
  return emu / EMU_PER_PX;
}

/** Does the [startRow, endRow] inclusive range intersect the viewport
 *  [vStart, vEnd] inclusive range? Cheap viewport-cull for overlay items. */
export function intersectsRowRange(
  startRow: number,
  endRow: number,
  vStart: number,
  vEnd: number,
): boolean {
  return startRow <= vEnd && endRow >= vStart;
}
