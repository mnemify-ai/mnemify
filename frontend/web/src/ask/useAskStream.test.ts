import { describe, expect, it } from "vitest";
import { extractCitationIds } from "./useAskStream";

describe("extractCitationIds", () => {
  it("dedupes in first-appearance order", () => {
    expect(extractCitationIds("Per [c3] and [c1], stable [c3].")).toEqual([
      "c3",
      "c1",
    ]);
  });

  it("returns empty for text without markers", () => {
    expect(extractCitationIds("no markers here")).toEqual([]);
    expect(extractCitationIds("")).toEqual([]);
  });

  it("ignores non-citation brackets", () => {
    expect(extractCitationIds("[note] [c12] [x1]")).toEqual(["c12"]);
  });
});
