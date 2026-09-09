import { describe, it, expect } from "vitest";
import {
  buildIndex,
  findMatches,
  groupMatchesByCell,
  highlightCellHtml,
  cellKey,
} from "./searchIndex";

function source(
  sheetIndex: number,
  sheetName: string,
  headers: string[],
  rows: string[][],
) {
  return {
    sheetIndex,
    sheetName,
    headers,
    rows: rows.map((r) => r.map((value) => ({ value }))),
  };
}

describe("buildIndex", () => {
  it("indexes headers at row 0 and data rows at row 1..N", () => {
    const idx = buildIndex([
      source(0, "S1", ["A", "B"], [
        ["a1", "b1"],
        ["a2", "b2"],
      ]),
    ]);
    expect(idx).toHaveLength(1);
    expect(idx[0].cells).toEqual([
      { r: 0, c: 0, text: "A" },
      { r: 0, c: 1, text: "B" },
      { r: 1, c: 0, text: "a1" },
      { r: 1, c: 1, text: "b1" },
      { r: 2, c: 0, text: "a2" },
      { r: 2, c: 1, text: "b2" },
    ]);
  });

  it("skips empty cells and empty headers", () => {
    const idx = buildIndex([
      source(0, "S1", ["A", ""], [["a1", ""], ["", "b2"]]),
    ]);
    expect(idx[0].cells).toEqual([
      { r: 0, c: 0, text: "A" },
      { r: 1, c: 0, text: "a1" },
      { r: 2, c: 1, text: "b2" },
    ]);
  });

  it("supports multiple sheets, each with its own sheetIndex", () => {
    const idx = buildIndex([
      source(0, "First", ["X"], [["x1"]]),
      source(1, "Second", ["Y"], [["y1"]]),
    ]);
    expect(idx).toHaveLength(2);
    expect(idx[0].sheetName).toBe("First");
    expect(idx[1].sheetName).toBe("Second");
  });
});

describe("findMatches", () => {
  const index = buildIndex([
    source(
      0,
      "S1",
      ["Customer", "Region"],
      [
        ["Acme Co", "North"],
        ["Acme Holdings", "South"],
      ],
    ),
    source(1, "S2", ["Notes"], [["acme is great"]]),
  ]);

  it("case-insensitive by default, scanning all sheets", () => {
    const matches = findMatches(index, "acme");
    expect(matches).toEqual([
      { sheetIndex: 0, row: 1, col: 0, startOffset: 0, endOffset: 4 },
      { sheetIndex: 0, row: 2, col: 0, startOffset: 0, endOffset: 4 },
      { sheetIndex: 1, row: 1, col: 0, startOffset: 0, endOffset: 4 },
    ]);
  });

  it("caseSensitive respects original case", () => {
    const matches = findMatches(index, "Acme", { caseSensitive: true });
    expect(matches).toHaveLength(2);
    expect(matches.every((m) => m.sheetIndex === 0)).toBe(true);
  });

  it("returns [] for empty query", () => {
    expect(findMatches(index, "")).toEqual([]);
  });

  it("finds overlapping needles ('aa' in 'aaaa' → 3 hits)", () => {
    const idx = buildIndex([source(0, "S", ["x"], [["aaaa"]])]);
    expect(findMatches(idx, "aa")).toHaveLength(3);
  });
});

describe("groupMatchesByCell", () => {
  it("groups matches keyed by sheetIndex:row:col", () => {
    const grouped = groupMatchesByCell([
      { sheetIndex: 0, row: 1, col: 0, startOffset: 0, endOffset: 3 },
      { sheetIndex: 0, row: 1, col: 0, startOffset: 10, endOffset: 13 },
      { sheetIndex: 0, row: 2, col: 1, startOffset: 0, endOffset: 4 },
    ]);
    expect(grouped.get(cellKey(0, 1, 0))).toHaveLength(2);
    expect(grouped.get(cellKey(0, 2, 1))).toHaveLength(1);
  });
});

describe("highlightCellHtml", () => {
  it("wraps in <mark> for non-active matches", () => {
    const html = highlightCellHtml(
      "Hello world",
      [{ sheetIndex: 0, row: 1, col: 0, startOffset: 6, endOffset: 11 }],
      null,
    );
    expect(html).toBe("Hello <mark>world</mark>");
  });

  it("marks the active match with data-active", () => {
    const match = {
      sheetIndex: 0,
      row: 1,
      col: 0,
      startOffset: 6,
      endOffset: 11,
    };
    const html = highlightCellHtml("Hello world", [match], match);
    expect(html).toBe('Hello <mark data-active="true">world</mark>');
  });

  it("escapes HTML in source text", () => {
    const html = highlightCellHtml(
      "<script>alert(1)</script>",
      [{ sheetIndex: 0, row: 1, col: 0, startOffset: 1, endOffset: 7 }],
      null,
    );
    expect(html).toBe("&lt;<mark>script</mark>&gt;alert(1)&lt;/script&gt;");
  });

  it("returns plain escaped text when no matches", () => {
    expect(highlightCellHtml("a & b", undefined, null)).toBe("a &amp; b");
  });

  it("handles multiple matches in a single cell", () => {
    const html = highlightCellHtml(
      "abc abc abc",
      [
        { sheetIndex: 0, row: 1, col: 0, startOffset: 0, endOffset: 3 },
        { sheetIndex: 0, row: 1, col: 0, startOffset: 4, endOffset: 7 },
        { sheetIndex: 0, row: 1, col: 0, startOffset: 8, endOffset: 11 },
      ],
      null,
    );
    expect(html).toBe("<mark>abc</mark> <mark>abc</mark> <mark>abc</mark>");
  });
});
