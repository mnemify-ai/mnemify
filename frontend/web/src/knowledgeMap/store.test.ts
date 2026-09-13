// Nav-layer + camera-nonce contract for the per-mount knowledge-map store.
//
// The nonce (`zoomToRegion`) is what CameraAnimator watches, and `idx: null`
// means "frame the whole map" (home) — not "do nothing". These tests pin the
// exact set of transitions that may emit it, because an over-eager emission
// yanks the camera out from under the user and a missing one leaves the orbit
// target stranded on a region peak after the focus clears.

import { describe, expect, it } from "vitest";
import { createKnowledgeMapStore } from "./store";

const store = () => createKnowledgeMapStore();

describe("navigate", () => {
  it("emits a region nonce when focus is set", () => {
    const s = store();
    s.getState().navigate({ focusRegionIdx: 3 });
    expect(s.getState().zoomToRegion).toEqual({ idx: 3, tick: 1 });
  });

  it("emits a home nonce when focus clears to null", () => {
    const s = store();
    s.getState().navigate({ focusRegionIdx: 3 });
    s.getState().navigate({ focusRegionIdx: null });
    expect(s.getState().zoomToRegion).toEqual({ idx: null, tick: 2 });
  });

  it("emits nothing for a null → null focus no-op", () => {
    const s = store();
    s.getState().navigate({ focusRegionIdx: null });
    expect(s.getState().zoomToRegion).toBeNull();
    expect(s.getState().navHistory).toHaveLength(0);
  });

  it("emits nothing when only the tag changes", () => {
    const s = store();
    s.getState().navigate({ selectedTagId: "tag.a" });
    expect(s.getState().selectedTagId).toBe("tag.a");
    expect(s.getState().zoomToRegion).toBeNull();
  });

  it("honours { zoom: false } in both directions", () => {
    const s = store();
    s.getState().navigate({ focusRegionIdx: 2 }, { zoom: false });
    expect(s.getState().zoomToRegion).toBeNull();
    s.getState().navigate({ focusRegionIdx: null }, { zoom: false });
    expect(s.getState().zoomToRegion).toBeNull();
  });
});

describe("back", () => {
  it("emits a home nonce stepping from a region back to the root", () => {
    const s = store();
    s.getState().navigate({ focusRegionIdx: 3 });
    s.getState().back();
    expect(s.getState().focusRegionIdx).toBeNull();
    expect(s.getState().zoomToRegion).toEqual({ idx: null, tick: 2 });
  });

  it("leaves the previous nonce untouched when back() restores the same focus", () => {
    const s = store();
    s.getState().navigate({ focusRegionIdx: 3 });
    // Selecting a tag inside the focused region: focus is unchanged, so
    // backing out of it must not re-frame anything.
    s.getState().navigate({ selectedTagId: "tag.a" });
    s.getState().back();
    expect(s.getState().zoomToRegion).toEqual({ idx: 3, tick: 1 });
  });

  it("emits nothing on empty history", () => {
    const s = store();
    s.getState().back();
    expect(s.getState().zoomToRegion).toBeNull();
  });
});

describe("resetNav", () => {
  it("emits a home nonce when a region was focused", () => {
    const s = store();
    s.getState().navigate({ focusRegionIdx: 3 });
    s.getState().resetNav();
    expect(s.getState().zoomToRegion).toEqual({ idx: null, tick: 2 });
    expect(s.getState().navHistory).toHaveLength(0);
  });

  it("emits nothing when only a tag was selected", () => {
    const s = store();
    s.getState().navigate({ selectedTagId: "tag.a" });
    s.getState().resetNav();
    expect(s.getState().selectedTagId).toBeNull();
    expect(s.getState().zoomToRegion).toBeNull();
    expect(s.getState().navHistory).toHaveLength(0);
  });
});

describe("home", () => {
  it("emits a home nonce even when already at the root", () => {
    const s = store();
    s.getState().home();
    expect(s.getState().zoomToRegion).toEqual({ idx: null, tick: 1 });
  });

  it("clears focus, tag, doc and history, and re-frames home", () => {
    const s = store();
    s.getState().navigate({ focusRegionIdx: 3 });
    s.getState().navigate({ selectedTagId: "tag.a" });
    s.getState().navigate({ docNoteId: "note.1" });
    s.getState().home();
    const st = s.getState();
    expect(st.focusRegionIdx).toBeNull();
    expect(st.selectedTagId).toBeNull();
    expect(st.docNoteId).toBeNull();
    expect(st.navHistory).toHaveLength(0);
    expect(st.zoomToRegion).toEqual({ idx: null, tick: 2 });
  });
});

describe("requestZoomToRegion", () => {
  it("emits a home nonce for null", () => {
    const s = store();
    s.getState().requestZoomToRegion(null);
    expect(s.getState().zoomToRegion).toEqual({ idx: null, tick: 1 });
  });

  it("ticks strictly upward across every emission", () => {
    const s = store();
    s.getState().requestZoomToRegion(1);
    s.getState().navigate({ focusRegionIdx: 2 });
    s.getState().back();
    s.getState().requestZoomToRegion(null);
    expect(s.getState().zoomToRegion?.tick).toBe(4);
  });
});

describe("legendHoverIdx", () => {
  it("starts null, sets, and clears", () => {
    const s = store();
    expect(s.getState().legendHoverIdx).toBeNull();
    s.getState().setLegendHover(4);
    expect(s.getState().legendHoverIdx).toBe(4);
    s.getState().setLegendHover(null);
    expect(s.getState().legendHoverIdx).toBeNull();
  });

  it("never touches the camera nonce", () => {
    const s = store();
    s.getState().setLegendHover(0);
    expect(s.getState().zoomToRegion).toBeNull();
  });
});
