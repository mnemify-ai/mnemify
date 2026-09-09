import { describe, it, expect, vi } from "vitest";
import {
  buildIndex,
  findMatches,
  groupMatchesByPage,
  createPageHighlighter,
  type PageText,
} from "./searchIndex";

// Synthetic pdf.js doc stand-in. The real PDFDocumentProxy is much richer;
// our buildIndex only needs numPages + getPage(n).getTextContent().
function fakeDoc(pages: Array<Array<{ str: string; hasEOL?: boolean }>>) {
  return {
    numPages: pages.length,
    getPage: async (n: number) => ({
      getTextContent: async () => ({ items: pages[n - 1] }),
    }),
  };
}

describe("buildIndex", () => {
  it("joins items and tracks per-item offsets, adding newlines after hasEOL", async () => {
    const doc = fakeDoc([
      [
        { str: "Hello " },
        { str: "world", hasEOL: true },
        { str: "next line" },
      ],
    ]);
    const onProgress = vi.fn();
    const index = await buildIndex(doc, onProgress, new AbortController().signal);
    expect(index).toHaveLength(1);
    expect(index[0].text).toBe("Hello world\nnext line");
    expect(index[0].itemOffsets).toEqual([0, 6, 12]);
    expect(onProgress).toHaveBeenCalledWith(1, 1);
  });

  it("reports progress per batch and yields PageText in page order", async () => {
    const doc = fakeDoc(
      Array.from({ length: 20 }, (_, i) => [{ str: `page${i + 1}` }]),
    );
    const onProgress = vi.fn();
    const index = await buildIndex(doc, onProgress, new AbortController().signal);
    expect(index.map((p) => p.text)).toEqual(
      Array.from({ length: 20 }, (_, i) => `page${i + 1}`),
    );
    // 20 pages, batch of 8 → progress called at 8, 16, 20.
    expect(onProgress.mock.calls.map((c) => c[0])).toEqual([8, 16, 20]);
  });

  it("substitutes an empty PageText for pages that throw, without stalling", async () => {
    const doc = {
      numPages: 3,
      getPage: async (n: number) => ({
        getTextContent: async () => {
          if (n === 2) throw new Error("boom");
          return { items: [{ str: `page${n}` }] };
        },
      }),
    };
    const onProgress = vi.fn();
    const index = await buildIndex(doc, onProgress, new AbortController().signal);
    expect(index[0].text).toBe("page1");
    expect(index[1].text).toBe("");
    expect(index[1].itemOffsets).toEqual([]);
    expect(index[2].text).toBe("page3");
  });

  it("aborts cleanly between batches when signaled", async () => {
    const doc = fakeDoc(
      Array.from({ length: 20 }, (_, i) => [{ str: `page${i + 1}` }]),
    );
    const ctl = new AbortController();
    const promise = buildIndex(doc, () => ctl.abort(), ctl.signal);
    await expect(promise).rejects.toThrow(/abort/i);
  });
});

describe("findMatches", () => {
  const index: PageText[] = [
    { pageNumber: 1, text: "The quick brown fox", itemOffsets: [0] },
    { pageNumber: 2, text: "Brown sugar and brown bread", itemOffsets: [0] },
    { pageNumber: 3, text: "", itemOffsets: [] },
  ];

  it("returns matches case-insensitively by default", () => {
    const matches = findMatches(index, "brown");
    expect(matches).toEqual([
      { pageNumber: 1, startOffset: 10, endOffset: 15 },
      { pageNumber: 2, startOffset: 0, endOffset: 5 },
      { pageNumber: 2, startOffset: 16, endOffset: 21 },
    ]);
  });

  it("respects caseSensitive opt", () => {
    const matches = findMatches(index, "brown", { caseSensitive: true });
    expect(matches).toEqual([
      { pageNumber: 1, startOffset: 10, endOffset: 15 },
      { pageNumber: 2, startOffset: 16, endOffset: 21 },
    ]);
  });

  it("finds overlapping matches (needle 'aa' in 'aaaa' → 3 hits)", () => {
    const idx: PageText[] = [
      { pageNumber: 1, text: "aaaa", itemOffsets: [0] },
    ];
    expect(findMatches(idx, "aa")).toHaveLength(3);
  });

  it("returns [] for empty query", () => {
    expect(findMatches(index, "")).toEqual([]);
  });

  it("skips pages with no text without throwing", () => {
    const matches = findMatches(index, "anything");
    expect(matches).toEqual([]);
  });
});

describe("groupMatchesByPage", () => {
  it("groups matches into per-page lists preserving order", () => {
    const grouped = groupMatchesByPage([
      { pageNumber: 1, startOffset: 0, endOffset: 3 },
      { pageNumber: 2, startOffset: 5, endOffset: 8 },
      { pageNumber: 1, startOffset: 10, endOffset: 13 },
    ]);
    expect(grouped.get(1)).toEqual([
      { pageNumber: 1, startOffset: 0, endOffset: 3 },
      { pageNumber: 1, startOffset: 10, endOffset: 13 },
    ]);
    expect(grouped.get(2)).toEqual([
      { pageNumber: 2, startOffset: 5, endOffset: 8 },
    ]);
  });
});

describe("createPageHighlighter", () => {
  // Item layout for "Hello world, hello again":
  //   item 0 "Hello "      offset  0, len 6  → covers [0,  6)
  //   item 1 "world"       offset  6, len 5  → covers [6, 11)
  //   item 2 ", "          offset 11, len 2  → covers [11,13)
  //   item 3 "hello again" offset 13, len 11 → covers [13,24)
  const page: PageText = {
    pageNumber: 1,
    text: "Hello world, hello again",
    itemOffsets: [0, 6, 11, 13],
  };

  it("returns null when no matches on page (caller skips re-render)", () => {
    expect(createPageHighlighter(page, [], null)).toBeNull();
  });

  it("wraps in-item matches in <mark>", () => {
    // 'hello' (case-insensitive index match) at offsets 0 and 13.
    const matches = [
      { pageNumber: 1, startOffset: 0, endOffset: 5 },
      { pageNumber: 1, startOffset: 13, endOffset: 18 },
    ];
    const render = createPageHighlighter(page, matches, null)!;
    // Item 0 = "Hello ", item 1 = "world", item 2 = ", ", item 3 = "hello again"
    // Reconstruct from itemOffsets: lengths are derived from str passed in.
    expect(render({ str: "Hello ", itemIndex: 0 })).toBe("<mark>Hello</mark> ");
    expect(render({ str: "world", itemIndex: 1 })).toBe("world");
    expect(render({ str: ", ", itemIndex: 2 })).toBe(", ");
    expect(render({ str: "hello again", itemIndex: 3 })).toBe(
      "<mark>hello</mark> again",
    );
  });

  it("marks the active match with data-active", () => {
    const matches = [
      { pageNumber: 1, startOffset: 0, endOffset: 5 },
      { pageNumber: 1, startOffset: 13, endOffset: 18 },
    ];
    const active = matches[1];
    const render = createPageHighlighter(page, matches, active)!;
    expect(render({ str: "Hello ", itemIndex: 0 })).toBe("<mark>Hello</mark> ");
    expect(render({ str: "hello again", itemIndex: 3 })).toBe(
      '<mark data-active="true">hello</mark> again',
    );
  });

  it("escapes HTML in source text so PDFs with < > & render safely", () => {
    const safe: PageText = {
      pageNumber: 1,
      text: "a <b>c & d</b> e",
      itemOffsets: [0],
    };
    const render = createPageHighlighter(safe, [
      { pageNumber: 1, startOffset: 2, endOffset: 5 },
    ], null)!;
    const out = render({ str: "a <b>c & d</b> e", itemIndex: 0 });
    expect(out).toContain("&lt;");
    expect(out).toContain("&amp;");
    expect(out).toContain("&gt;");
    // The <mark> tag itself must not be escaped.
    expect(out).toMatch(/<mark>.*<\/mark>/);
  });

  it("handles matches that span across text items (cross-item slice)", () => {
    // 'world, hello' spans items 1, 2, 3.
    const matches = [{ pageNumber: 1, startOffset: 6, endOffset: 18 }];
    const render = createPageHighlighter(page, matches, null)!;
    expect(render({ str: "Hello ", itemIndex: 0 })).toBe("Hello ");
    expect(render({ str: "world", itemIndex: 1 })).toBe("<mark>world</mark>");
    expect(render({ str: ", ", itemIndex: 2 })).toBe("<mark>, </mark>");
    expect(render({ str: "hello again", itemIndex: 3 })).toBe(
      "<mark>hello</mark> again",
    );
  });
});
