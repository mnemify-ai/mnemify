import { beforeEach, describe, expect, it } from "vitest";
import { useMapFocusStore } from "./mapFocusStore";
import { useMapHighlightStore } from "./mapHighlightStore";

describe("mapFocusStore.requestFocus", () => {
  beforeEach(() => {
    useMapHighlightStore.getState().clear();
    useMapFocusStore.setState({ focusRegionId: null, focusTick: 0 });
  });

  it("bumps the tick even for the region already focused", () => {
    const s = useMapFocusStore.getState();
    s.requestFocus("r1");
    s.requestFocus("r1");
    expect(useMapFocusStore.getState().focusRegionId).toBe("r1");
    expect(useMapFocusStore.getState().focusTick).toBe(2);
  });

  it("claims the camera from the current answer highlight", () => {
    useMapHighlightStore.getState().setHighlight({
      tagIds: [],
      regionIds: ["a", "b"],
      noteIds: [],
      label: "q",
    });
    const token = useMapHighlightStore.getState().highlight!.token;
    useMapFocusStore.getState().requestFocus("r1");
    expect(useMapHighlightStore.getState().cameraClaimedToken).toBe(token);
  });

  it("setFocusRegion (the map's own echo) leaves the tick alone", () => {
    useMapFocusStore.getState().setFocusRegion("r2");
    expect(useMapFocusStore.getState().focusTick).toBe(0);
  });
});
