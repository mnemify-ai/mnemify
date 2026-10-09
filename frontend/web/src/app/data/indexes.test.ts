import { describe, expect, it } from "vitest";
import { buildIndexes } from "./indexes";
import type { NotesFile, RenderData } from "./types";

const renderData = {
  version: 3,
  regions: [
    { id: "r", name: "R", level: 0, parentIdx: -1, isLeaf: false, color: "#000", accent: null, centroid: { x: 0, z: 0 }, radius: 1, basePlateauHeight: 0, tagCount: 0, avgElevation: 0 },
    { id: "c1", name: "C1", level: 1, parentIdx: 0, isLeaf: true, color: "#000", accent: null, centroid: { x: 0, z: 0 }, radius: 1, basePlateauHeight: 0, tagCount: 1, avgElevation: 0 },
    { id: "c2", name: "C2", level: 1, parentIdx: 0, isLeaf: true, color: "#000", accent: null, centroid: { x: 0, z: 0 }, radius: 1, basePlateauHeight: 0, tagCount: 0, avgElevation: 0 },
  ],
  hexes: [],
  tagIndex: [],
  arcs: [],
} as unknown as RenderData;
const notes = { version: 2, generatedAt: null, notes: [] } as unknown as NotesFile;

describe("buildIndexes.childrenByRegionId", () => {
  it("lists direct children in bake order, and empty arrays for leaves", () => {
    const idx = buildIndexes(renderData, notes);
    expect(idx.childrenByRegionId.get("r")?.map((r) => r.id)).toEqual(["c1", "c2"]);
    expect(idx.childrenByRegionId.get("c1")).toEqual([]);
  });
});
