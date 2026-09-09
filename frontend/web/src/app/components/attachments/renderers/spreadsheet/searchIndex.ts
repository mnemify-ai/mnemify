// Cell-level search index for the spreadsheet viewer.
//
// Browser Cmd/Ctrl-F can't see virtualized rows (~30 mounted of 50k), and
// it doesn't cross sheet boundaries. So we maintain our own index across
// every sheet, scan it for the user's query, and cycle through matches
// with auto-sheet-switch + scroll-to-cell.
//
// Index addressing convention: row 0 = header row (sticky); rows 1..N = data
// rows. This mirrors what users see and what they'd type into a Go-To-Cell
// box. The orchestrator converts row 1..N back to virtualizer index r-1.

export interface CellEntry {
  r: number; // 0 = header; 1..N = data rows
  c: number;
  text: string;
}

export interface SheetIndex {
  sheetIndex: number;
  sheetName: string;
  cells: CellEntry[];
}

export type SheetSearchIndex = SheetIndex[];

export interface Match {
  sheetIndex: number;
  row: number;
  col: number;
  /** Char offset within the cell's text where the match begins. */
  startOffset: number;
  endOffset: number;
}

export interface FindOptions {
  caseSensitive?: boolean;
}

interface SheetSource {
  sheetIndex: number;
  sheetName: string;
  headers: string[];
  rows: Array<Array<{ value: string }>>;
}

/** Build the per-sheet index synchronously. For sheets > ~50k cells, prefer
 *  buildIndexChunked which yields control between batches. */
export function buildIndex(sources: SheetSource[]): SheetSearchIndex {
  return sources.map(buildOneSheet);
}

function buildOneSheet(source: SheetSource): SheetIndex {
  const cells: CellEntry[] = [];
  for (let c = 0; c < source.headers.length; c++) {
    const text = source.headers[c];
    if (text) cells.push({ r: 0, c, text });
  }
  for (let r = 0; r < source.rows.length; r++) {
    const row = source.rows[r];
    for (let c = 0; c < row.length; c++) {
      const text = row[c]?.value;
      if (text) cells.push({ r: r + 1, c, text });
    }
  }
  return { sheetIndex: source.sheetIndex, sheetName: source.sheetName, cells };
}

/**
 * Async chunked builder. Yields to the browser every `chunkSize` cells via
 * MessageChannel (more reliable than setTimeout(0) and faster than rIC for
 * our use). Calls onProgress after each chunk so partial matches can
 * surface in the UI while the index is still building.
 */
export async function buildIndexChunked(
  sources: SheetSource[],
  onProgress: (built: SheetSearchIndex) => void,
  signal: AbortSignal,
  chunkSize = 5000,
): Promise<SheetSearchIndex> {
  const result: SheetSearchIndex = [];
  let processedSinceYield = 0;
  for (const source of sources) {
    if (signal.aborted) throw new DOMException("aborted", "AbortError");
    const index: SheetIndex = {
      sheetIndex: source.sheetIndex,
      sheetName: source.sheetName,
      cells: [],
    };
    // Headers first.
    for (let c = 0; c < source.headers.length; c++) {
      const t = source.headers[c];
      if (t) index.cells.push({ r: 0, c, text: t });
    }
    // Body in chunks.
    for (let r = 0; r < source.rows.length; r++) {
      const row = source.rows[r];
      for (let c = 0; c < row.length; c++) {
        const t = row[c]?.value;
        if (t) index.cells.push({ r: r + 1, c, text: t });
      }
      processedSinceYield += row.length;
      if (processedSinceYield >= chunkSize) {
        result[source.sheetIndex] = { ...index, cells: index.cells.slice() };
        onProgress([...result]);
        await yieldToBrowser();
        if (signal.aborted) throw new DOMException("aborted", "AbortError");
        processedSinceYield = 0;
      }
    }
    result[source.sheetIndex] = index;
    onProgress([...result]);
  }
  return result;
}

/** Yield control via MessageChannel — runs after pending tasks without the
 *  4ms minimum delay browsers apply to setTimeout(0). */
function yieldToBrowser(): Promise<void> {
  return new Promise((resolve) => {
    const channel = new MessageChannel();
    channel.port1.onmessage = () => resolve();
    channel.port2.postMessage(null);
  });
}

export function findMatches(
  index: SheetSearchIndex,
  query: string,
  opts: FindOptions = {},
): Match[] {
  if (!query) return [];
  const needle = opts.caseSensitive ? query : query.toLowerCase();
  if (!needle) return [];
  const matches: Match[] = [];
  for (const sheet of index) {
    if (!sheet) continue;
    for (const cell of sheet.cells) {
      const haystack = opts.caseSensitive ? cell.text : cell.text.toLowerCase();
      let pos = 0;
      while (true) {
        const found = haystack.indexOf(needle, pos);
        if (found === -1) break;
        matches.push({
          sheetIndex: sheet.sheetIndex,
          row: cell.r,
          col: cell.c,
          startOffset: found,
          endOffset: found + needle.length,
        });
        // Advance by 1 to allow overlapping matches.
        pos = found + 1;
      }
    }
  }
  return matches;
}

/** Map (sheetIndex, row, col) → matches for that cell, for cheap per-cell
 *  lookup during render. */
export function groupMatchesByCell(
  matches: Match[],
): Map<string, Match[]> {
  const m = new Map<string, Match[]>();
  for (const match of matches) {
    const key = cellKey(match.sheetIndex, match.row, match.col);
    let list = m.get(key);
    if (!list) {
      list = [];
      m.set(key, list);
    }
    list.push(match);
  }
  return m;
}

export function cellKey(sheetIndex: number, row: number, col: number): string {
  return `${sheetIndex}:${row}:${col}`;
}

/**
 * Highlight a cell's text by wrapping match slices in <mark>. The active
 * match (if it's in this cell) gets data-active="true" for the stronger
 * highlight color. Returns the original text when no matches apply.
 *
 * Returns an HTML string. The caller injects via dangerouslySetInnerHTML —
 * we escape source text so cell values containing < > & don't get parsed.
 */
export function highlightCellHtml(
  text: string,
  matchesInCell: Match[] | undefined,
  activeMatch: Match | null,
): string {
  if (!matchesInCell || matchesInCell.length === 0) return escapeHtml(text);
  // Matches are produced in source order; assume sorted by startOffset.
  let out = "";
  let cursor = 0;
  for (const m of matchesInCell) {
    if (m.startOffset > cursor) out += escapeHtml(text.slice(cursor, m.startOffset));
    const isActive =
      activeMatch !== null &&
      m.sheetIndex === activeMatch.sheetIndex &&
      m.row === activeMatch.row &&
      m.col === activeMatch.col &&
      m.startOffset === activeMatch.startOffset;
    out += `<mark${isActive ? ' data-active="true"' : ""}>${escapeHtml(
      text.slice(m.startOffset, m.endOffset),
    )}</mark>`;
    cursor = m.endOffset;
  }
  if (cursor < text.length) out += escapeHtml(text.slice(cursor));
  return out;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
