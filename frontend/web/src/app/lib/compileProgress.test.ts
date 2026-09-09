import { describe, it, expect } from "vitest";
import { countsFromSnapshot, enrichCountLine, stageLabel } from "./compileProgress";
import type { CompileCountsState } from "../sse/useCompileStream";

const EMPTY: CompileCountsState = {
  docs: 0, chunks: 0, enrichPhase: null, enrichDone: 0, enrichTotal: 0,
  enrichExtractDone: 0, enrichExtractTotal: 0, enrichEmbedDone: 0, enrichEmbedTotal: 0,
  deriveDone: 0, deriveTotal: 0,
};

const counts = (over: Partial<CompileCountsState> = {}): CompileCountsState => ({
  ...EMPTY,
  ...over,
});

describe("stageLabel", () => {
  it("counts chunks during the extract phase of enrich", () => {
    expect(
      stageLabel("enrich", counts({ enrichPhase: "extract", enrichDone: 214, enrichTotal: 815 })),
    ).toBe("Analyzing chunks 214 / 815");
  });

  it("switches the verb during the embed phase of enrich", () => {
    expect(
      stageLabel("enrich", counts({ enrichPhase: "embed", enrichDone: 40, enrichTotal: 815 })),
    ).toBe("Embedding 40 / 815");
  });

  it("falls back to the phase name during enrich before a total is known", () => {
    expect(stageLabel("enrich", counts({ enrichPhase: "extract" }))).toBe(
      "Compiling · Understanding each piece",
    );
  });

  it("uses the plain phase name for non-enrich stages", () => {
    expect(stageLabel("cluster", counts())).toBe("Compiling · Finding patterns");
    expect(stageLabel("derive", counts({ deriveDone: 3, deriveTotal: 9 }))).toBe(
      "Compiling · Naming regions & tags",
    );
  });

  it("passes an unknown stage through verbatim, and ellipsizes a missing one", () => {
    expect(stageLabel("quantizing", counts())).toBe("Compiling · quantizing");
    expect(stageLabel(null, counts())).toBe("Compiling · …");
    expect(stageLabel(undefined, counts())).toBe("Compiling · …");
  });
});

describe("enrichCountLine", () => {
  it("is null until a total is known", () => {
    expect(enrichCountLine(counts())).toBeNull();
    expect(enrichCountLine(counts({ enrichDone: 5 }))).toBeNull();
  });

  it("defaults to the extract verb when no phase has been reported", () => {
    expect(enrichCountLine(counts({ enrichDone: 1, enrichTotal: 8 }))).toBe(
      "Analyzing chunks 1 / 8",
    );
  });
});

describe("countsFromSnapshot", () => {
  it("zero-fills an absent snapshot", () => {
    expect(countsFromSnapshot(undefined)).toEqual(EMPTY);
  });

  it("widens the snake_case poll payload into the camelCase state", () => {
    expect(
      countsFromSnapshot({
        docs: 12,
        chunks: 815,
        enrich_phase: "embed",
        enrich_done: 40,
        enrich_total: 815,
        enrich_extract_done: 815,
        enrich_extract_total: 815,
        enrich_embed_done: 40,
        enrich_embed_total: 815,
        derive_done: 2,
        derive_total: 7,
        // Carried on the snapshot for the pill's ETA — not part of the state.
        rate_per_sec: 3.5,
      }),
    ).toEqual({
      docs: 12,
      chunks: 815,
      enrichPhase: "embed",
      enrichDone: 40,
      enrichTotal: 815,
      enrichExtractDone: 815,
      enrichExtractTotal: 815,
      enrichEmbedDone: 40,
      enrichEmbedTotal: 815,
      deriveDone: 2,
      deriveTotal: 7,
    });
  });
});
