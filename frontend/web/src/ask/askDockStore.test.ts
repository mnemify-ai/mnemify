import { describe, expect, it } from "vitest";
import { dockInsetCss, dockOverlayInset } from "./askDockStore";

// The single rule every right-anchored overlay in the app now shares: how far
// in from the viewport's right edge it has to stop so it lands beside the Ask
// dock rather than on top of the conversation.

describe("dockOverlayInset", () => {
  it("is zero when the dock is closed — nothing to clear", () => {
    expect(dockOverlayInset({ open: false, wide: false, width: 460 })).toBe(0);
  });

  it("is the docked width when the dock is open", () => {
    expect(dockOverlayInset({ open: true, wide: false, width: 460 })).toBe(460);
    expect(dockOverlayInset({ open: true, wide: false, width: 380 })).toBe(380);
  });

  it("is zero when maximized — a full-row dock leaves no room beside it", () => {
    // Surfaces that must not cover the dock un-maximize it on the way in
    // (openOverlay), so this branch is what they see for one render at most.
    expect(dockOverlayInset({ open: true, wide: true, width: 460 })).toBe(0);
  });

  it("ignores a stale width while closed", () => {
    expect(dockOverlayInset({ open: false, wide: true, width: 900 })).toBe(0);
  });
});

describe("dockInsetCss", () => {
  // The store keeps a width dragged on a 27" monitor verbatim; the dock's
  // aside re-clamps it to the current viewport in CSS. The inset has to carry
  // the *same* clamp or it describes a dock edge that isn't there.
  it("mirrors the aside's own viewport ceiling", () => {
    expect(dockInsetCss(460)).toBe("min(460px, 92vw, calc(100vw - 420px))");
  });

  it("clamps a width dragged on a wider monitor rather than overshooting", () => {
    // On a 1440px laptop the dock renders min(1800, 1324.8, 1020) = 1020px.
    // The min() resolves to the same 1020, so the overlay lands flush instead
    // of leaving a 780px gap and driving calc(100vw - inset) negative.
    expect(dockInsetCss(1800)).toBe("min(1800px, 92vw, calc(100vw - 420px))");
  });

  it("still resolves to zero when the dock is closed", () => {
    // Consumers apply this behind `md:`, where the other two terms are always
    // positive, so min() with a 0px term is 0px.
    expect(dockInsetCss(0)).toBe("min(0px, 92vw, calc(100vw - 420px))");
  });
});
