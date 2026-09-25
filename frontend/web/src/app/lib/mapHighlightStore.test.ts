import { beforeEach, describe, expect, it } from "vitest";
import { useMapHighlightStore } from "./mapHighlightStore";

const ids = { tagIds: ["t1"], regionIds: ["r1"], noteIds: ["n-1"] };

describe("mapHighlightStore", () => {
  beforeEach(() => useMapHighlightStore.getState().clear());

  it("setHighlight mints a new token each time", () => {
    const s = useMapHighlightStore.getState();
    s.setHighlight({ ...ids, label: "q1" });
    const a = useMapHighlightStore.getState().highlight!.token;
    s.setHighlight({ ...ids, label: "q2" });
    const b = useMapHighlightStore.getState().highlight!.token;
    expect(b).toBeGreaterThan(a);
  });

  it("narrow keeps the token and label", () => {
    const s = useMapHighlightStore.getState();
    s.setHighlight({ ...ids, label: "q" });
    const before = useMapHighlightStore.getState().highlight!;
    s.narrow({ tagIds: ["t1"], regionIds: [], noteIds: [] });
    const after = useMapHighlightStore.getState().highlight!;
    expect(after.token).toBe(before.token);
    expect(after.label).toBe("q");
    expect(after.regionIds).toEqual([]);
  });

  it("narrow is a no-op with nothing highlighted", () => {
    useMapHighlightStore.getState().narrow(ids);
    expect(useMapHighlightStore.getState().highlight).toBeNull();
  });

  it("clear is identity-stable when already empty", () => {
    const before = useMapHighlightStore.getState();
    before.clear();
    expect(useMapHighlightStore.getState().highlight).toBeNull();
  });
});
