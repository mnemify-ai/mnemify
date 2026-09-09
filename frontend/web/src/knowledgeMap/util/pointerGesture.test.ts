// Pins the click-vs-drag contract that stops an orbit gesture from drilling
// into a region. The boundary is INCLUSIVE — a tap that wobbles exactly
// CLICK_MAX_DRAG_PX still counts as a click — and a real camera drag, which is
// tens of pixels, never does.

import { describe, expect, it } from "vitest";
import { CLICK_MAX_DRAG_PX, isClickNotDrag } from "./pointerGesture";

describe("isClickNotDrag", () => {
  it("treats a perfectly still press as a click", () => {
    expect(isClickNotDrag(0)).toBe(true);
  });

  it("tolerates jitter up to and including the threshold", () => {
    expect(isClickNotDrag(CLICK_MAX_DRAG_PX)).toBe(true);
  });

  it("rejects one pixel past the threshold", () => {
    expect(isClickNotDrag(CLICK_MAX_DRAG_PX + 1)).toBe(false);
  });

  it("rejects a real orbit drag", () => {
    expect(isClickNotDrag(120)).toBe(false);
  });

  it("stays more tolerant than r3f's own 2px pointer-missed heuristic", () => {
    expect(CLICK_MAX_DRAG_PX).toBeGreaterThan(2);
  });
});
