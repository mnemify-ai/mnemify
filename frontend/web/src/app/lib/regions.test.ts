import { describe, expect, it } from "vitest";
import type { MemoryGroup, MemoryItem } from "../api/regions";
import type { Note, RegionEntry } from "../data/types";
import {
  filterActionItemsToRegion,
  groupMemoryBySubregion,
  isInSubtree,
  lastTouchedAt,
  memoryTitleFromQuestion,
  sourcesBreakdown,
  stripCitationMarkers,
} from "./regions";

function region(id: string, level: number, parentIdx: number): RegionEntry {
  return {
    id, name: id.toUpperCase(), level, parentIdx, isLeaf: level > 0, color: "#000", accent: null,
    centroid: { x: 0, z: 0 }, radius: 1, basePlateauHeight: 0, tagCount: 0, avgElevation: 0,
  };
}
const root = region("root", 0, -1);
const a = region("a", 1, 0);
const b = region("b", 1, 0);
const a1 = region("a1", 2, 1);
const regionPathById = new Map<string, RegionEntry[]>([
  ["root", [root]], ["a", [root, a]], ["b", [root, b]], ["a1", [root, a, a1]],
]);
const childrenByRegionId = new Map<string, RegionEntry[]>([
  ["root", [a, b]], ["a", [a1]], ["b", []], ["a1", []],
]);

function note(id: string, source: string, updatedAt: string): Note {
  return { id, title: id, source, sourceUrl: "", author: "", createdAt: updatedAt, updatedAt, regionId: "a", primaryTagId: "t", tagIds: ["t"], excerpt: "", wordCount: 1 };
}
function mem(id: string, region_id: string): MemoryItem {
  return { id, region_key: "k", region_id, region_name: region_id, title: id, body: "", kind: "answer", citations: [], source_note_ids: [], origin: {}, created_at: "", updated_at: "" };
}

describe("isInSubtree", () => {
  it("includes self and descendants, excludes siblings", () => {
    expect(isInSubtree(regionPathById, "a", "a")).toBe(true);
    expect(isInSubtree(regionPathById, "a", "a1")).toBe(true);
    expect(isInSubtree(regionPathById, "a", "b")).toBe(false);
    expect(isInSubtree(regionPathById, "a", null)).toBe(false);
  });
});

describe("sourcesBreakdown / lastTouchedAt", () => {
  const notes = [note("1", "notion", "2026-01-02"), note("2", "confluence", "2026-03-01"), note("3", "notion", "2025-12-01")];
  it("counts most common first", () => {
    expect(sourcesBreakdown(notes)).toEqual([{ source: "notion", count: 2 }, { source: "confluence", count: 1 }]);
  });
  it("finds the latest stamp", () => {
    expect(lastTouchedAt(notes)).toBe("2026-03-01");
    expect(lastTouchedAt([])).toBeNull();
  });
});

describe("filterActionItemsToRegion", () => {
  it("keeps subtree items that aren't dismissed", () => {
    const base = { title: "", summary: "", severity: 0, status: "open", owner: null, due_date: null, due_text: null, days_until_due: null, bucket: "no_date" as const, source_note_ids: [], source_chunk_ids: [], region_label: null, tag_id: null, tag_label: null };
    const items = [
      { ...base, id: "x", region_id: "a1", user_status: "unverified" as const },
      { ...base, id: "y", region_id: "b", user_status: "unverified" as const },
      { ...base, id: "z", region_id: "a", user_status: "dismissed" as const },
    ];
    expect(filterActionItemsToRegion(items, regionPathById, "a").map((i) => i.id)).toEqual(["x"]);
  });
});

describe("stripCitationMarkers / memoryTitleFromQuestion", () => {
  it("removes [cN] markers and tidies spacing", () => {
    expect(stripCitationMarkers("Alpha is key [c1]; see also [c2] [c3]. Done [c4]")).toBe("Alpha is key; see also. Done");
  });
  it("derives a bounded title", () => {
    expect(memoryTitleFromQuestion("  what   is  alpha? ")).toBe("what is alpha?");
    expect(memoryTitleFromQuestion("x".repeat(100)).length).toBe(64);
    expect(memoryTitleFromQuestion("")).toBe("Saved finding");
  });
});

describe("groupMemoryBySubregion", () => {
  it("puts self first and rolls deeper regions up to the direct child", () => {
    const groups: MemoryGroup[] = [
      { region_id: "root", region_name: "ROOT", is_self: true, path: ["ROOT"], items: [mem("m0", "root")] },
      { region_id: "a1", region_name: "A1", is_self: false, path: ["ROOT", "A", "A1"], items: [mem("m1", "a1")] },
      { region_id: "a", region_name: "A", is_self: false, path: ["ROOT", "A"], items: [mem("m2", "a")] },
    ];
    const out = groupMemoryBySubregion(groups, "root", childrenByRegionId, regionPathById);
    expect(out.map((s) => [s.id, s.items.map((m) => m.id)])).toEqual([
      ["root", ["m0"]],
      ["a", ["m1", "m2"]],
    ]);
  });
  it("always emits the self section even when empty", () => {
    const out = groupMemoryBySubregion([], "b", childrenByRegionId, regionPathById);
    expect(out).toEqual([{ id: "b", title: "This region", isSelf: true, items: [] }]);
  });
});
