import { describe, expect, it } from "vitest";
import { resolvePulseRegionIdxs } from "./agentPulse";
import type { RenderData, RegionEntry } from "../types";

/** regions: 0 top-level, 1 child of 0, 2 grandchild of 1, 3 another top. */
function fixture(): RenderData {
  const region = (id: string, parentIdx: number, level: number): RegionEntry =>
    ({
      id,
      name: id,
      level,
      parentIdx,
      isLeaf: true,
      color: "#000",
      accent: "#000",
      centroid: { x: 0, z: 0 },
      radius: 1,
      basePlateauHeight: 1,
      tagCount: 0,
      notes: 0,
      sources: 0,
      avgElevation: 0,
      attentionScore: 0,
      attentionLevel: "none",
    }) as unknown as RegionEntry;
  return {
    regions: [
      region("top_a", -1, 0),
      region("child_a", 0, 1),
      region("grandchild_a", 1, 2),
      region("top_b", -1, 0),
    ],
  } as unknown as RenderData;
}

describe("resolvePulseRegionIdxs", () => {
  it("walks a nested region up to the top-level medallion", () => {
    // The map only draws medallions for level-0 regions, so a pulse on a
    // leaf sub-region has to climb or it lights nothing.
    expect(resolvePulseRegionIdxs(fixture(), ["grandchild_a"])).toEqual(new Set([0]));
    expect(resolvePulseRegionIdxs(fixture(), ["child_a"])).toEqual(new Set([0]));
  });

  it("keeps a top-level region as itself", () => {
    expect(resolvePulseRegionIdxs(fixture(), ["top_b"])).toEqual(new Set([3]));
  });

  it("collapses siblings under one ancestor to a single pulse", () => {
    expect(
      resolvePulseRegionIdxs(fixture(), ["child_a", "grandchild_a", "top_a"]),
    ).toEqual(new Set([0]));
  });

  it("ignores ids that aren't regions in this bake", () => {
    expect(resolvePulseRegionIdxs(fixture(), ["node_note", ""])).toEqual(new Set());
  });

  it("survives a parent cycle instead of hanging", () => {
    const data = fixture();
    data.regions[0].parentIdx = 1; // top_a ↔ child_a cycle
    expect(() => resolvePulseRegionIdxs(data, ["grandchild_a"])).not.toThrow();
  });
});
