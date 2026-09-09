import { describe, it, expect } from "vitest";
import {
  buildGeometry,
  effectiveColWidths,
  effectiveRowHeights,
  emuToPx,
  intersectsRowRange,
  projectMerge,
  EMU_PER_PX,
} from "./geometry";

describe("buildGeometry", () => {
  it("computes cumulative prefix sums with sentinel end values", () => {
    const g = buildGeometry([100, 200, 50], [20, 30, 40, 50]);
    expect(g.colLefts).toEqual([0, 100, 300, 350]);
    expect(g.rowTops).toEqual([0, 20, 50, 90, 140]);
  });

  it("handles empty inputs", () => {
    const g = buildGeometry([], []);
    expect(g.colLefts).toEqual([0]);
    expect(g.rowTops).toEqual([0]);
  });
});

describe("effectiveColWidths", () => {
  it("zeroes hidden, prefers overrides, applies zoom", () => {
    const out = effectiveColWidths({
      baseWidths: [100, 200, 50, 80],
      overrides: { 1: 300 },
      hidden: new Set([2]),
      zoom: 1.5,
    });
    expect(out).toEqual([150, 450, 0, 120]);
  });
});

describe("effectiveRowHeights", () => {
  it("works symmetrically to columns", () => {
    const out = effectiveRowHeights({
      baseHeights: [32, 32, 32],
      overrides: { 0: 64 },
      hidden: new Set([1]),
      zoom: 1,
    });
    expect(out).toEqual([64, 0, 32]);
  });
});

describe("projectMerge", () => {
  it("projects merge bounds via cumulative caches", () => {
    const g = buildGeometry([100, 100, 100, 100], [30, 30, 30]);
    // Merge from (r=0,c=1) to (r=1,c=2) — 2x2 block spanning cols 1-2, rows 0-1.
    const rect = projectMerge(g, 0, 1, 1, 2);
    expect(rect).toEqual({ left: 100, top: 0, width: 200, height: 60 });
  });

  it("handles a 1x1 merge (degenerate but legal)", () => {
    const g = buildGeometry([100, 100], [30, 30]);
    expect(projectMerge(g, 0, 0, 0, 0)).toEqual({
      left: 0,
      top: 0,
      width: 100,
      height: 30,
    });
  });

  it("collapses through hidden columns/rows automatically", () => {
    // Hide column 1 (width 0). Merge across cols 0-2 should equal w(0)+w(2).
    const widths = effectiveColWidths({
      baseWidths: [100, 100, 100],
      overrides: {},
      hidden: new Set([1]),
      zoom: 1,
    });
    const g = buildGeometry(widths, [30, 30]);
    const rect = projectMerge(g, 0, 0, 0, 2);
    expect(rect.width).toBe(200);
  });
});

describe("emuToPx", () => {
  it("converts EMU to CSS px using the 9525 constant", () => {
    expect(emuToPx(EMU_PER_PX)).toBe(1);
    expect(emuToPx(EMU_PER_PX * 10)).toBe(10);
  });

  it("returns 0 for nullish input (anchor offsets are often undefined)", () => {
    expect(emuToPx(undefined)).toBe(0);
    expect(emuToPx(null)).toBe(0);
    expect(emuToPx(0)).toBe(0);
  });
});

describe("intersectsRowRange", () => {
  it("returns true for overlapping ranges", () => {
    expect(intersectsRowRange(5, 10, 8, 15)).toBe(true);
    expect(intersectsRowRange(0, 100, 50, 50)).toBe(true);
    expect(intersectsRowRange(3, 3, 3, 3)).toBe(true);
  });

  it("returns false for disjoint ranges", () => {
    expect(intersectsRowRange(0, 5, 10, 15)).toBe(false);
    expect(intersectsRowRange(20, 25, 0, 10)).toBe(false);
  });

  it("includes boundary touches as overlap", () => {
    expect(intersectsRowRange(0, 5, 5, 10)).toBe(true);
    expect(intersectsRowRange(5, 10, 0, 5)).toBe(true);
  });
});
