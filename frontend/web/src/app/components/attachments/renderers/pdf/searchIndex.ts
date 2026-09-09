// Pure text-search subsystem for the PDF viewer.
//
// Browser Cmd/Ctrl-F only sees text-layer DOM for the currently-mounted
// virtualized pages (~5 of however many), so we maintain our own index over
// the whole document and highlight matches via react-pdf's customTextRenderer.
//
// Three concerns live here, all framework-agnostic:
//   1. buildIndex — extract per-page text + per-item char offsets from pdf.js
//   2. findMatches — substring scan across the index
//   3. createHighlighter — return a customTextRenderer that wraps matches in
//      <mark>, with the active match getting data-active="true"
//
// Kept side-effect-free so the matcher + highlighter are unit-testable
// without spinning up a pdf.js worker.
//
// Indexing strategy: batched (8 pages in flight) Promise.allSettled.
// pdf.js getTextContent runs in the worker, so the main thread cost is the
// proxy hop + our string concat. ~3–8s for a 500-page document.

export interface PageText {
  pageNumber: number;
  /** Joined item strings (item separator = ""; newline appended after items
   *  flagged `hasEOL` by pdf.js). Used as the haystack for indexOf. */
  text: string;
  /** itemOffsets[i] = char offset in `text` where text item i begins.
   *  Lets us map a global match range back to per-item slices for
   *  highlighting. */
  itemOffsets: number[];
}

export interface Match {
  pageNumber: number;
  /** Char offset within `PageText.text` where the match begins. */
  startOffset: number;
  /** Exclusive end offset. */
  endOffset: number;
}

export interface FindOptions {
  caseSensitive?: boolean;
}

/** Minimal pdf.js duck-typing — keeps this module test-friendly.
 *  Matches the shape of pdf.js's PDFDocumentProxy / PDFPageProxy for the
 *  methods we touch. getTextContent returns a mix of TextItem (which has
 *  `str`) and TextMarkedContent (which doesn't) — we filter to the former. */
interface PdfDocLike {
  numPages: number;
  getPage: (n: number) => Promise<PdfPageLike>;
}
interface PdfPageLike {
  getTextContent: () => Promise<{
    items: Array<{ str?: string; hasEOL?: boolean } | unknown>;
  }>;
}

const BATCH_SIZE = 8;

export async function buildIndex(
  pdf: PdfDocLike,
  onProgress: (done: number, total: number) => void,
  signal: AbortSignal,
): Promise<PageText[]> {
  const total = pdf.numPages;
  const results: PageText[] = new Array(total);
  let done = 0;

  for (let start = 1; start <= total; start += BATCH_SIZE) {
    if (signal.aborted) {
      throw new DOMException("Indexing aborted", "AbortError");
    }
    const end = Math.min(start + BATCH_SIZE - 1, total);
    const batch: Promise<void>[] = [];
    for (let n = start; n <= end; n++) {
      const pageNumber = n;
      batch.push(
        (async () => {
          try {
            const page = await pdf.getPage(pageNumber);
            const tc = await page.getTextContent();
            // Filter out TextMarkedContent (no `str`); we only index real text.
            const items = tc.items.filter(isTextItem);
            results[pageNumber - 1] = buildPageText(pageNumber, items);
          } catch {
            // A single broken page shouldn't stall search across the doc.
            results[pageNumber - 1] = emptyPage(pageNumber);
          }
        })(),
      );
    }
    await Promise.allSettled(batch);
    done = end;
    onProgress(done, total);
  }

  return results;
}

function isTextItem(item: unknown): item is { str: string; hasEOL?: boolean } {
  return typeof item === "object" && item !== null && typeof (item as { str?: unknown }).str === "string";
}

function buildPageText(
  pageNumber: number,
  items: Array<{ str: string; hasEOL?: boolean }>,
): PageText {
  const itemOffsets: number[] = new Array(items.length);
  let text = "";
  for (let i = 0; i < items.length; i++) {
    itemOffsets[i] = text.length;
    text += items[i].str;
    if (items[i].hasEOL) text += "\n";
  }
  return { pageNumber, text, itemOffsets };
}

function emptyPage(pageNumber: number): PageText {
  return { pageNumber, text: "", itemOffsets: [] };
}

export function findMatches(
  index: PageText[],
  query: string,
  opts: FindOptions = {},
): Match[] {
  if (!query) return [];
  const matches: Match[] = [];
  const needle = opts.caseSensitive ? query : query.toLowerCase();
  if (!needle) return [];

  for (const page of index) {
    if (!page || !page.text) continue;
    const haystack = opts.caseSensitive ? page.text : page.text.toLowerCase();
    let pos = 0;
    // String.indexOf is O(n*m) worst-case but ~free in practice for
    // English text; no need for KMP unless queries get pathological.
    while (true) {
      const found = haystack.indexOf(needle, pos);
      if (found === -1) break;
      matches.push({
        pageNumber: page.pageNumber,
        startOffset: found,
        endOffset: found + needle.length,
      });
      // Advance by 1 to allow overlapping matches ("aaaa" / "aa" → 3 hits).
      pos = found + 1;
    }
  }
  return matches;
}

/** Map page number → its matches, for quick per-page lookup during render. */
export function groupMatchesByPage(matches: Match[]): Map<number, Match[]> {
  const m = new Map<number, Match[]>();
  for (const match of matches) {
    let list = m.get(match.pageNumber);
    if (!list) {
      list = [];
      m.set(match.pageNumber, list);
    }
    list.push(match);
  }
  return m;
}

export type CustomTextRendererFn = (props: {
  str: string;
  itemIndex: number;
}) => string;

/**
 * Returns a customTextRenderer (per-page) that wraps matched slices in <mark>.
 * The active match (if on this page) gets `data-active="true"` for the
 * stronger highlight color defined in pdf.css.
 *
 * Returns null if there are no matches on this page — the caller should
 * pass `undefined` to <Page> in that case, since react-pdf re-lays out the
 * text layer whenever the renderer ref changes.
 */
export function createPageHighlighter(
  page: PageText,
  matchesOnPage: Match[],
  activeMatch: Match | null,
): CustomTextRendererFn | null {
  if (matchesOnPage.length === 0) return null;

  return ({ str, itemIndex }) => {
    const itemStart = page.itemOffsets[itemIndex] ?? 0;
    const itemEnd = itemStart + str.length;

    // Matches whose char range intersects this item.
    const overlapping: Match[] = [];
    for (const m of matchesOnPage) {
      if (m.endOffset > itemStart && m.startOffset < itemEnd) {
        overlapping.push(m);
      }
    }
    if (overlapping.length === 0) return escapeHtml(str);

    let out = "";
    let cursor = 0;
    for (const m of overlapping) {
      const localStart = Math.max(0, m.startOffset - itemStart);
      const localEnd = Math.min(str.length, m.endOffset - itemStart);
      if (localStart > cursor) out += escapeHtml(str.slice(cursor, localStart));
      const isActive =
        activeMatch !== null &&
        m.pageNumber === activeMatch.pageNumber &&
        m.startOffset === activeMatch.startOffset;
      out += `<mark${isActive ? ' data-active="true"' : ""}>${escapeHtml(
        str.slice(localStart, localEnd),
      )}</mark>`;
      cursor = localEnd;
    }
    if (cursor < str.length) out += escapeHtml(str.slice(cursor));
    return out;
  };
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
