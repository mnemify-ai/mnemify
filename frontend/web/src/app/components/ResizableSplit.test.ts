// The split fraction is stored as user intent and re-projected onto whatever
// width the container actually has — the Ask dock opening beside /documents
// takes ~460px out of the row without the window changing size at all. Every
// case here is stated as a *pane width*, because that's the thing that was
// broken: a fraction can look reasonable and still leave the right pane 121px
// under its minimum.

import { describe, expect, it } from "vitest";
import { SPLIT_DIVIDER_PX, clampSplitFraction } from "./ResizableSplit";

// The /documents pair (see DocumentsPage's SPLIT_MIN_* constants).
const MIN_LEFT = 420;
const MIN_RIGHT = 360;

const leftWidth = (f: number, w: number) => f * w;
const rightWidth = (f: number, w: number) => w - f * w - SPLIT_DIVIDER_PX;

describe("clampSplitFraction", () => {
  it("leaves a fraction both panes can afford alone", () => {
    const f = clampSplitFraction(0.55, 980, MIN_LEFT, MIN_RIGHT);
    expect(f).toBe(0.55);
    expect(leftWidth(f, 980)).toBeGreaterThanOrEqual(MIN_LEFT);
    expect(rightWidth(f, 980)).toBeGreaterThanOrEqual(MIN_RIGHT);
  });

  it("rescues the right pane when the Ask dock narrows the container", () => {
    // Dragged fully right at 1440 with the dock closed, then the dock opens at
    // 460 → 980px of container. Unclamped this left the viewer 239px wide.
    const f = clampSplitFraction(0.75, 980, MIN_LEFT, MIN_RIGHT);
    expect(rightWidth(f, 980)).toBeCloseTo(MIN_RIGHT, 6);
    expect(leftWidth(f, 980)).toBeGreaterThan(MIN_LEFT);
  });

  it("rescues the left pane when the fraction is dragged too far left", () => {
    const f = clampSplitFraction(0.2, 980, MIN_LEFT, MIN_RIGHT);
    expect(leftWidth(f, 980)).toBeCloseTo(MIN_LEFT, 6);
    expect(rightWidth(f, 980)).toBeGreaterThan(MIN_RIGHT);
  });

  it("splits in proportion to the minimums when neither can be met", () => {
    // 420 + 6 + 360 = 786 > 700, so no fraction satisfies both.
    const w = 700;
    const f = clampSplitFraction(0.75, w, MIN_LEFT, MIN_RIGHT);
    const left = leftWidth(f, w);
    const right = rightWidth(f, w);
    expect(left + right + SPLIT_DIVIDER_PX).toBeCloseTo(w, 6);
    // Both panes fall short by the same ratio — neither collapses.
    expect(left / right).toBeCloseTo(MIN_LEFT / MIN_RIGHT, 6);
    expect(left).toBeLessThan(MIN_LEFT);
    expect(right).toBeLessThan(MIN_RIGHT);
  });

  it("passes the fraction through before the container has been measured", () => {
    // The first render runs with width 0; the layout effect measures after.
    expect(clampSplitFraction(0.75, 0, MIN_LEFT, MIN_RIGHT)).toBe(0.75);
    expect(clampSplitFraction(0.75, NaN, MIN_LEFT, MIN_RIGHT)).toBe(0.75);
    expect(clampSplitFraction(0.75, -10, MIN_LEFT, MIN_RIGHT)).toBe(0.75);
  });
});
