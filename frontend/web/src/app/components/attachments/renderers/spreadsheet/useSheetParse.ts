// Two-stage parser hook.
//
// Stage 1 (sync, fast): SheetJS. Drives the first paint of the table — cell
// values, basic numeric typing, sheet names. Handles .xlsx, .xls, .csv.
//
// Stage 2 (async, lazy chunk): ExcelJS. Only loaded for .xlsx files. Adds
// what SheetJS open-source doesn't expose: merged cells, embedded images
// (with anchor offsets), cell styles (fonts, colors, fills, alignment),
// column widths set by the document. Failures here never block the SheetJS
// view — we log + continue.
//
// Address convention: row 0 = header row, rows 1..N = data rows. This
// matches both the renderer's display layout and the searchIndex's
// indexing, so a single (row, col) tuple is the universal cell address.

import { useEffect, useMemo, useState } from "react";
import * as XLSX from "xlsx";
import { useAttachmentBlob } from "../../useAttachmentBlob";
import type { ExcelStyle } from "./cellFormatting";

const ROW_HEIGHT = 32;
const DEFAULT_COL_WIDTH = 140;
const MIN_COL_WIDTH = 96;
const MAX_COL_WIDTH = 360;
const COL_WIDTH_SAMPLE = 200;

export interface CellView {
  value: string;
  numeric: boolean;
}

export interface SheetMerge {
  s: { r: number; c: number };
  e: { r: number; c: number };
}

export interface SheetImage {
  id: string;
  tlCol: number;
  tlRow: number;
  tlColOffsetEmu?: number;
  tlRowOffsetEmu?: number;
  brCol?: number;
  brRow?: number;
  brColOffsetEmu?: number;
  brRowOffsetEmu?: number;
  extWidthPx?: number;
  extHeightPx?: number;
  /** Image dimensions in Excel's own pixel space (computed at parse time
   *  using Excel's actual column widths and row heights). Used to size the
   *  image independently of our wider, sample-estimated display columns —
   *  otherwise images get stretched to fill our roomy grid. */
  nativeWidthPx: number;
  nativeHeightPx: number;
  blobUrl: string;
}

export interface ParsedSheet {
  name: string;
  headers: string[];
  rows: CellView[][];
  baseColWidths: number[];
  baseRowHeights: number[];
  merges: SheetMerge[];
  images: SheetImage[];
  /** Keyed by `${r}:${c}` where r=0 is header row, r=1..N data rows. */
  styles: Map<string, ExcelStyle>;
}

export interface ParsedWorkbook {
  sheets: ParsedSheet[];
  /** True once ExcelJS metadata has been merged in (or attempted). */
  extended: boolean;
}

export interface ParseResult {
  status: "loading" | "ready" | "error";
  workbook: ParsedWorkbook | null;
  error?: Error;
  /** True while ExcelJS parse is in flight after SheetJS already resolved. */
  extending: boolean;
  refetch: () => void;
}

export function useSheetParse(
  inlineUrl: string,
  filename: string,
): ParseResult {
  const blob = useAttachmentBlob(inlineUrl);

  // Stage 1: SheetJS — sync useMemo so first paint doesn't wait.
  const baseWorkbook = useMemo(() => {
    if (!blob.data) return null;
    try {
      return parseWithSheetJs(blob.data);
    } catch (e) {
      console.warn("[useSheetParse] SheetJS parse failed", e);
      return null;
    }
  }, [blob.data]);

  // Stage 2: ExcelJS — only for .xlsx. Runs after SheetJS settles.
  const [extended, setExtended] = useState<ParsedSheet[] | null>(null);
  const [extending, setExtending] = useState(false);

  const isXlsx = filename.toLowerCase().endsWith(".xlsx");

  useEffect(() => {
    if (!blob.data || !baseWorkbook || !isXlsx) {
      setExtended(null);
      return;
    }
    let cancelled = false;
    const objectUrls: string[] = [];
    setExtending(true);
    (async () => {
      try {
        const ExcelJS = await import("exceljs");
        if (cancelled) return;
        const enriched = await enrichWithExcelJs(
          ExcelJS,
          blob.data!,
          baseWorkbook,
          objectUrls,
        );
        if (cancelled) {
          // Revoke any URLs we created if we got cancelled mid-flight.
          for (const url of objectUrls) URL.revokeObjectURL(url);
          return;
        }
        setExtended(enriched);
      } catch (e) {
        console.warn("[useSheetParse] ExcelJS enrichment failed", e);
        // Leave extended=null so the renderer falls back to SheetJS-only.
      } finally {
        if (!cancelled) setExtending(false);
      }
    })();
    return () => {
      cancelled = true;
      for (const url of objectUrls) URL.revokeObjectURL(url);
    };
  }, [blob.data, baseWorkbook, isXlsx]);

  const workbook: ParsedWorkbook | null = useMemo(() => {
    if (!baseWorkbook) return null;
    return {
      sheets: extended ?? baseWorkbook,
      extended: extended !== null,
    };
  }, [baseWorkbook, extended]);

  if (blob.isLoading) {
    return { status: "loading", workbook: null, extending: false, refetch: () => void blob.refetch() };
  }
  if (blob.isError) {
    return {
      status: "error",
      workbook: null,
      error: blob.error instanceof Error ? blob.error : new Error("Load failed"),
      extending: false,
      refetch: () => void blob.refetch(),
    };
  }
  if (!workbook) {
    return {
      status: "error",
      workbook: null,
      error: new Error("Could not parse spreadsheet"),
      extending: false,
      refetch: () => void blob.refetch(),
    };
  }
  return {
    status: "ready",
    workbook,
    extending,
    refetch: () => void blob.refetch(),
  };
}

// --------------------------------------------------------------- SheetJS

function parseWithSheetJs(buffer: ArrayBuffer): ParsedSheet[] {
  const wb = XLSX.read(buffer, { type: "array", cellDates: true });
  const out: ParsedSheet[] = [];
  for (const name of wb.SheetNames) {
    const ws = wb.Sheets[name];
    if (!ws || !ws["!ref"]) {
      out.push(emptySheet(name));
      continue;
    }
    const range = XLSX.utils.decode_range(ws["!ref"]);
    const cols = range.e.c - range.s.c + 1;

    const headers: string[] = new Array(cols);
    for (let c = 0; c < cols; c++) {
      const addr = XLSX.utils.encode_cell({ r: range.s.r, c: range.s.c + c });
      const cell = ws[addr];
      headers[c] = cell?.w ?? (cell?.v != null ? String(cell.v) : "");
    }

    const rowCount = range.e.r - range.s.r; // excludes header
    const rows: CellView[][] = new Array(Math.max(0, rowCount));
    for (let r = 0; r < rowCount; r++) {
      const rowCells: CellView[] = new Array(cols);
      const sheetRow = range.s.r + 1 + r;
      for (let c = 0; c < cols; c++) {
        const addr = XLSX.utils.encode_cell({ r: sheetRow, c: range.s.c + c });
        const cell = ws[addr];
        if (!cell) {
          rowCells[c] = { value: "", numeric: false };
          continue;
        }
        const value =
          cell.w ??
          (cell.v instanceof Date
            ? cell.v.toISOString().slice(0, 10)
            : cell.v != null
              ? String(cell.v)
              : "");
        rowCells[c] = { value, numeric: cell.t === "n" };
      }
      rows[r] = rowCells;
    }

    out.push({
      name,
      headers,
      rows,
      baseColWidths: estimateColWidths(headers, rows),
      baseRowHeights: new Array(rows.length).fill(ROW_HEIGHT),
      merges: [],
      images: [],
      styles: new Map(),
    });
  }
  return out;
}

function emptySheet(name: string): ParsedSheet {
  return {
    name,
    headers: [],
    rows: [],
    baseColWidths: [],
    baseRowHeights: [],
    merges: [],
    images: [],
    styles: new Map(),
  };
}

function estimateColWidths(headers: string[], rows: CellView[][]): number[] {
  const cols = headers.length;
  const widths = new Array<number>(cols);
  for (let c = 0; c < cols; c++) {
    let maxLen = headers[c]?.length ?? 0;
    const sample = Math.min(COL_WIDTH_SAMPLE, rows.length);
    for (let r = 0; r < sample; r++) {
      const len = rows[r][c]?.value?.length ?? 0;
      if (len > maxLen) maxLen = len;
    }
    const px = Math.min(MAX_COL_WIDTH, Math.max(MIN_COL_WIDTH, maxLen * 7.5 + 24));
    widths[c] = Number.isFinite(px) ? px : DEFAULT_COL_WIDTH;
  }
  return widths;
}

// --------------------------------------------------------------- ExcelJS

type ExcelJsModule = typeof import("exceljs");

/** Enrich SheetJS-derived sheets with ExcelJS metadata. Returns a NEW array
 *  (does not mutate baseSheets). On per-sheet failure, falls through with
 *  that sheet's base data unchanged. */
async function enrichWithExcelJs(
  ExcelJS: ExcelJsModule,
  buffer: ArrayBuffer,
  baseSheets: ParsedSheet[],
  objectUrls: string[],
): Promise<ParsedSheet[]> {
  const wb = new ExcelJS.Workbook();
  await wb.xlsx.load(buffer);

  return baseSheets.map((base) => {
    try {
      const ws = wb.getWorksheet(base.name);
      if (!ws) return base;
      return enrichOneSheet(ws, base, wb, objectUrls);
    } catch (e) {
      console.warn(`[useSheetParse] ExcelJS enrich for sheet "${base.name}" failed`, e);
      return base;
    }
  });
}

function enrichOneSheet(
  ws: import("exceljs").Worksheet,
  base: ParsedSheet,
  wb: import("exceljs").Workbook,
  objectUrls: string[],
): ParsedSheet {
  // Merges. ExcelJS exposes the merges Object as { "A1:B2": "A1", ... };
  // we convert each range key to {s, e} addresses in 0-based row/col aligned
  // to our display convention (header at row 0, data at row 1+). ExcelJS's
  // own row indices are 1-based, mirroring Excel.
  const merges: SheetMerge[] = [];
  // @ts-expect-error - ExcelJS's _merges is the runtime source of truth here;
  // the public `getCell().isMerged` doesn't expose the bounds in one call.
  const mergeMap: Record<string, string> = ws._merges || {};
  for (const rangeKey of Object.keys(mergeMap)) {
    const parsed = parseRangeKey(rangeKey);
    if (parsed) merges.push(parsed);
  }

  // Images.
  const images: SheetImage[] = [];
  const wsImages: Array<{ imageId: string; range: ImgRange }> = (
    ws as unknown as { getImages?: () => Array<{ imageId: string; range: ImgRange }> }
  ).getImages?.() ?? [];
  const sizer = makeExcelSizer(ws);
  for (const img of wsImages) {
    // ExcelJS exposes media as an indexed array; getImages() returns the
    // image's position-as-string in `imageId`.
    const idx = Number.parseInt(img.imageId, 10);
    const model = Number.isFinite(idx) ? wb.model.media[idx] : undefined;
    if (!model || !model.buffer) continue;
    const mime = mimeForExt(model.extension);
    const blob = new Blob([model.buffer], { type: mime });
    const url = URL.createObjectURL(blob);
    objectUrls.push(url);

    const tl = img.range.tl;
    const br = img.range.br;
    const ext = img.range.ext;
    const native = computeImageNativeSize(sizer, img.range);
    images.push({
      id: `${ws.id}-${images.length}`,
      tlCol: tl.nativeCol,
      tlRow: tl.nativeRow,
      tlColOffsetEmu: tl.nativeColOff ?? 0,
      tlRowOffsetEmu: tl.nativeRowOff ?? 0,
      brCol: br?.nativeCol,
      brRow: br?.nativeRow,
      brColOffsetEmu: br?.nativeColOff ?? 0,
      brRowOffsetEmu: br?.nativeRowOff ?? 0,
      extWidthPx: ext?.width,
      extHeightPx: ext?.height,
      nativeWidthPx: native.width,
      nativeHeightPx: native.height,
      blobUrl: url,
    });
  }

  // Cell styles. Walk only cells that have a style — iterate ExcelJS rows.
  const styles = new Map<string, ExcelStyle>();
  ws.eachRow({ includeEmpty: false }, (row, sheetRowNum) => {
    // sheetRowNum is 1-based. Our display row 0 = header (ExcelJS row 1),
    // display row r = ExcelJS row r+1.
    const displayRow = sheetRowNum - 1;
    row.eachCell({ includeEmpty: false }, (cell, sheetColNum) => {
      const displayCol = sheetColNum - 1;
      // Only store when there's actually a style worth applying.
      if (hasMeaningfulStyle(cell.style)) {
        styles.set(`${displayRow}:${displayCol}`, cell.style as ExcelStyle);
      }
    });
  });

  // Column widths from the document. ExcelJS reports them in Excel "character
  // units" (~7px each); only override our sample-estimated widths when the
  // doc explicitly set one, since defaults from the doc often differ from
  // what a viewer needs.
  const baseColWidths = base.baseColWidths.slice();
  if (ws.columns) {
    ws.columns.forEach((col, i) => {
      if (col && typeof col.width === "number" && col.width > 0) {
        const px = Math.round(col.width * 7);
        baseColWidths[i] = Math.min(
          MAX_COL_WIDTH * 2, // doc widths can be larger than our sample cap
          Math.max(MIN_COL_WIDTH, px),
        );
      }
    });
  }

  return {
    ...base,
    merges,
    images,
    styles,
    baseColWidths,
  };
}

// ExcelJS exposes range cells as Anchor instances whose .model serializes
// to `{ nativeCol, nativeColOff, nativeRow, nativeRowOff }` (1-based row/col,
// EMU offsets). The Anchor class also has `col`/`row` getters that return
// a fractional value (nativeCol + offset/colWidth), which we previously
// relied on — but coercing a float through array indexing is fragile and
// the `colWidth` denominator inside the getter is an ExcelJS-internal scale,
// not real EMU. Read the native integer fields directly instead.
interface AnchorModel {
  nativeCol: number;
  nativeRow: number;
  nativeColOff?: number;
  nativeRowOff?: number;
}
interface ImgRange {
  tl: AnchorModel;
  br?: AnchorModel;
  ext?: { width: number; height: number };
}

function parseRangeKey(key: string): SheetMerge | null {
  // "A1:B2" → s/e coords. Display rows: header at row 0, data starts at 1.
  // ExcelJS encodes addresses using Excel A1 notation (1-based row).
  const parts = key.split(":");
  if (parts.length !== 2) return null;
  const s = decodeA1(parts[0]);
  const e = decodeA1(parts[1]);
  if (!s || !e) return null;
  return { s, e };
}

function decodeA1(addr: string): { r: number; c: number } | null {
  const match = /^([A-Z]+)([0-9]+)$/.exec(addr);
  if (!match) return null;
  const colLetters = match[1];
  const row1Based = parseInt(match[2], 10);
  let col = 0;
  for (let i = 0; i < colLetters.length; i++) {
    col = col * 26 + (colLetters.charCodeAt(i) - 64);
  }
  // ExcelJS row 1 = our display row 0 (header), row 2 = display row 1, etc.
  return { r: row1Based - 1, c: col - 1 };
}

function mimeForExt(ext: string | undefined): string {
  switch (ext) {
    case "png":
      return "image/png";
    case "jpeg":
    case "jpg":
      return "image/jpeg";
    case "gif":
      return "image/gif";
    case "bmp":
      return "image/bmp";
    case "svg":
      return "image/svg+xml";
    default:
      return "application/octet-stream";
  }
}

// Excel pixel size for an image span.
//
// Why this exists: our display columns are widened (estimateColWidths /
// sample-based) for readability, so projecting an image's two-cell anchor
// against `geometry.colLefts` makes the image balloon to fill our roomy
// columns. Computing the size against Excel's own widths and heights pins
// the image to its Excel-rendered size; the renderer just needs to position
// it at the right top-left and scale by zoom.
//
// Falls back to ExcelJS's `ext` if it's present (it usually is for
// one-cell anchors); otherwise sums Excel's per-column / per-row pixel
// extents, adjusting for the EMU offsets inside the anchor cells.

const EMU_PER_PX_LOCAL = 9525;
const EXCEL_DEFAULT_COL_WIDTH_CHARS = 8.43;
const EXCEL_DEFAULT_ROW_HEIGHT_PTS = 15;
const PX_PER_EXCEL_CHAR = 7; // 11pt Calibri default rendering
// Hard ceiling for any embedded image's native size. Some Excel docs anchor
// a logo across dozens of columns at full PNG resolution; without this the
// image dwarfs the rest of the sheet at any zoom. Aspect ratio is preserved.
// These caps are at 100% zoom — at lower zooms the image shrinks
// proportionally, so even legitimately-sized logos stay legible.
const MAX_IMAGE_NATIVE_W = 1000;
const MAX_IMAGE_NATIVE_H = 600;

interface ExcelSizer {
  colWidthPx: (col0: number) => number;
  rowHeightPx: (row0: number) => number;
}

function makeExcelSizer(ws: import("exceljs").Worksheet): ExcelSizer {
  // Defaults from worksheet properties when set; fall back to Excel's
  // built-ins. ExcelJS occasionally exposes these on different shapes
  // (`properties.defaultColWidth` vs `defaultColWidth`); be defensive.
  const props = (ws as unknown as {
    properties?: { defaultColWidth?: number; defaultRowHeight?: number };
    defaultColWidth?: number;
    defaultRowHeight?: number;
  });
  const defaultColChars =
    props.properties?.defaultColWidth ??
    props.defaultColWidth ??
    EXCEL_DEFAULT_COL_WIDTH_CHARS;
  const defaultRowPts =
    props.properties?.defaultRowHeight ??
    props.defaultRowHeight ??
    EXCEL_DEFAULT_ROW_HEIGHT_PTS;

  return {
    colWidthPx(col0: number): number {
      // ExcelJS is 1-based; col0 is our 0-based index.
      const col = ws.getColumn(col0 + 1);
      const chars =
        col && typeof col.width === "number" && col.width > 0
          ? col.width
          : defaultColChars;
      return chars * PX_PER_EXCEL_CHAR;
    },
    rowHeightPx(row0: number): number {
      const row = ws.getRow(row0 + 1);
      const pts =
        row && typeof row.height === "number" && row.height > 0
          ? row.height
          : defaultRowPts;
      return (pts * 96) / 72;
    },
  };
}

function computeImageNativeSize(
  sizer: ExcelSizer,
  range: ImgRange,
): { width: number; height: number } {
  let width = 0;
  let height = 0;

  // ExcelJS's ext path: width/height are already in CSS pixels (the parser
  // divides cx/cy by 9525 EMU). One-cell anchors always carry ext;
  // two-cell anchors leave it undefined and we fall through.
  const ext = range.ext;
  if (
    ext &&
    typeof ext.width === "number" &&
    typeof ext.height === "number" &&
    ext.width > 0 &&
    ext.height > 0
  ) {
    width = ext.width;
    height = ext.height;
  } else if (range.br) {
    const tlCol = range.tl.nativeCol ?? 0;
    const tlRow = range.tl.nativeRow ?? 0;
    const brCol = range.br.nativeCol ?? 0;
    const brRow = range.br.nativeRow ?? 0;

    const tlColOff = (range.tl.nativeColOff ?? 0) / EMU_PER_PX_LOCAL;
    const tlRowOff = (range.tl.nativeRowOff ?? 0) / EMU_PER_PX_LOCAL;
    const brColOff = (range.br.nativeColOff ?? 0) / EMU_PER_PX_LOCAL;
    const brRowOff = (range.br.nativeRowOff ?? 0) / EMU_PER_PX_LOCAL;

    width = -tlColOff;
    for (let c = tlCol; c < brCol; c++) width += sizer.colWidthPx(c);
    width += brColOff;

    height = -tlRowOff;
    for (let r = tlRow; r < brRow; r++) height += sizer.rowHeightPx(r);
    height += brRowOff;
  }

  width = Math.max(0, width);
  height = Math.max(0, height);

  // Clamp aspect-preserving so an over-eagerly-resized image never dwarfs
  // the rest of the sheet.
  if (width > MAX_IMAGE_NATIVE_W || height > MAX_IMAGE_NATIVE_H) {
    const scale = Math.min(MAX_IMAGE_NATIVE_W / width, MAX_IMAGE_NATIVE_H / height);
    width = Math.round(width * scale);
    height = Math.round(height * scale);
  }

  return { width, height };
}

function hasMeaningfulStyle(s: unknown): boolean {
  if (!s || typeof s !== "object") return false;
  const style = s as ExcelStyle;
  return !!(
    style.font?.bold ||
    style.font?.italic ||
    style.font?.underline ||
    style.font?.strike ||
    style.font?.size ||
    style.font?.color?.argb ||
    (style.fill?.type === "pattern" && style.fill.fgColor?.argb) ||
    style.alignment?.horizontal ||
    style.alignment?.vertical ||
    style.alignment?.wrapText ||
    style.alignment?.indent
  );
}
