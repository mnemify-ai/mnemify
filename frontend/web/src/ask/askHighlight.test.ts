import { describe, expect, it } from "vitest";
import { highlightFromCitations, usedCitations } from "./askHighlight";
import type { Citation } from "./types";

const cite = (over: Partial<Citation>): Citation => ({
  citation_id: "c1",
  node_id: "x",
  node_type: "note",
  layer: 0,
  label: "",
  edge_provenance: null,
  ...over,
});

describe("highlightFromCitations", () => {
  it("routes each node type to the right bucket", () => {
    const out = highlightFromCitations([
      cite({ citation_id: "c1", node_type: "tag", node_id: "tag.a", home_region_id: "r1" }),
      cite({ citation_id: "c2", node_type: "region", node_id: "r2" }),
      cite({ citation_id: "c3", node_type: "note", node_id: "n-1", home_region_id: "r1" }),
    ]);
    expect(out.tagIds).toEqual(["tag.a"]);
    expect(out.regionIds).toEqual(["r1", "r2"]);
    expect(out.noteIds).toEqual(["n-1"]);
  });

  it("entities contribute their source notes, or their home region", () => {
    const out = highlightFromCitations([
      cite({ citation_id: "c1", node_type: "entity", node_id: "e1", source_note_ids: ["n-9"] }),
      cite({ citation_id: "c2", node_type: "signal", node_id: "s1", home_region_id: "r5" }),
    ]);
    expect(out.noteIds).toEqual(["n-9"]);
    expect(out.regionIds).toEqual(["r5"]);
  });

  it("dedupes", () => {
    const out = highlightFromCitations([
      cite({ citation_id: "c1", node_type: "tag", node_id: "t" }),
      cite({ citation_id: "c2", node_type: "tag", node_id: "t" }),
    ]);
    expect(out.tagIds).toEqual(["t"]);
  });
});

describe("usedCitations", () => {
  const all = [cite({ citation_id: "c1" }), cite({ citation_id: "c2" })];
  it("filters to the used ids", () => {
    expect(usedCitations(all, ["c2"]).map((c) => c.citation_id)).toEqual(["c2"]);
  });
  it("keeps everything when nothing was used", () => {
    expect(usedCitations(all, [])).toHaveLength(2);
  });
});
