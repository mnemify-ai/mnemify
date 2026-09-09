import { describe, it, expect } from "vitest";
import { applyCompileEvent, type CompileStreamState } from "./useCompileStream";

const EMPTY: CompileStreamState = {
  status: "idle",
  stage: null,
  counts: {
    docs: 0, chunks: 0, enrichPhase: null, enrichDone: 0, enrichTotal: 0,
    enrichExtractDone: 0, enrichExtractTotal: 0, enrichEmbedDone: 0, enrichEmbedTotal: 0,
    deriveDone: 0, deriveTotal: 0,
  },
  rate: null,
  summary: null,
  error: null,
  logs: [],
  connected: false,
};

let keyN = 0;
const nextKey = () => String(++keyN);

describe("applyCompileEvent reducer", () => {
  it("learns the enrich denominator from the chunk event and tracks progress", () => {
    let s = applyCompileEvent(EMPTY, { type: "progress", stage: "load", count: 12, ts: 0 }, nextKey);
    expect(s.counts.docs).toBe(12);
    expect(s.status).toBe("running");
    s = applyCompileEvent(s, { type: "progress", stage: "chunk", total: 40, ts: 0 }, nextKey);
    expect(s.counts.enrichTotal).toBe(40);
    expect(s.counts.enrichDone).toBe(0);
    s = applyCompileEvent(s, { type: "progress", stage: "enrich", done: 1, total: 40, cached: false, rate_per_sec: 3, ts: 0 }, nextKey);
    expect(s.counts.enrichDone).toBe(1);
    expect(s.rate).toBe(3); // first non-null sample seeds the EWMA
  });

  it("doesn't tick the rate on cached chunks", () => {
    let s = applyCompileEvent(EMPTY, { type: "progress", stage: "enrich", done: 1, total: 10, cached: false, rate_per_sec: 4, ts: 0 }, nextKey);
    expect(s.rate).toBe(4);
    // a cached chunk arrives with rate_per_sec === null
    s = applyCompileEvent(s, { type: "progress", stage: "enrich", done: 2, total: 10, cached: true, rate_per_sec: null, ts: 0 }, nextKey);
    expect(s.rate).toBe(4); // unchanged
    expect(s.counts.enrichDone).toBe(2);
  });

  it("tracks the derive (naming) phase", () => {
    let s = applyCompileEvent(EMPTY, { type: "progress", stage: "derive", done: 0, total: 30, ts: 0 }, nextKey);
    expect(s.counts.deriveTotal).toBe(30);
    s = applyCompileEvent(s, { type: "progress", stage: "derive", done: 7, total: 30, ts: 0 }, nextKey);
    expect(s.counts.deriveDone).toBe(7);
    expect(s.stage).toBe("derive");
  });

  it("tracks the enrich extract → embed phases separately", () => {
    let s = applyCompileEvent(EMPTY, { type: "progress", stage: "chunk", total: 40, ts: 0 }, nextKey);
    s = applyCompileEvent(s, { type: "progress", stage: "enrich", phase: "extract", done: 10, total: 40, rate_per_sec: 2, ts: 0 }, nextKey);
    expect(s.counts.enrichPhase).toBe("extract");
    expect(s.counts.enrichExtractDone).toBe(10);
    expect(s.counts.enrichExtractTotal).toBe(40);
    expect(s.counts.enrichDone).toBe(10);
    s = applyCompileEvent(s, { type: "progress", stage: "enrich", phase: "embed", done: 3, total: 40, ts: 0 }, nextKey);
    expect(s.counts.enrichPhase).toBe("embed");
    expect(s.counts.enrichEmbedDone).toBe(3);
    expect(s.counts.enrichExtractDone).toBe(10); // extract counts preserved
  });

  it("appends log/error entries with fresh keys, capped at the buffer", () => {
    let s = EMPTY;
    for (let i = 0; i < 250; i++) {
      s = applyCompileEvent(s, { type: "log", level: "info", stage: "enrich", msg: `m${i}`, ts: i }, nextKey);
    }
    expect(s.logs.length).toBe(200);
    expect(s.logs[0].msg).toBe("m249"); // newest first
    expect(new Set(s.logs.map((l) => l.key)).size).toBe(s.logs.length);
    s = applyCompileEvent(s, { type: "error", level: "error", stage: "render", msg: "boom", ts: 9999 }, nextKey);
    expect(s.logs[0]).toMatchObject({ level: "error", stage: "render", msg: "boom" });
  });

  it("settles on complete and on failed", () => {
    const stats = { regions: 5, subRegionsTotal: 12, tagsTotal: 30, notes: 80, sources: 2, edges: 14 };
    let s = applyCompileEvent(EMPTY, { type: "complete", run_id: "terrain_abc", ai_mode: "local", seconds: 7, stats, ts: 0 }, nextKey);
    expect(s.status).toBe("complete");
    expect(s.summary).toMatchObject({ run_id: "terrain_abc", ai_mode: "local", seconds: 7 });
    expect(s.summary?.stats.regions).toBe(5);
    s = applyCompileEvent(EMPTY, { type: "failed", error: "OPENAI_API_KEY not set", ts: 0 }, nextKey);
    expect(s.status).toBe("failed");
    expect(s.error).toBe("OPENAI_API_KEY not set");
  });

  it("takes status + counts from a snapshot", () => {
    const s = applyCompileEvent(EMPTY, {
      type: "snapshot",
      state: {
        status: "running",
        stage: "enrich",
        counts: { docs: 9, chunks: 22, enrich_done: 4, enrich_total: 22, derive_done: 0, derive_total: 0 },
        summary: null,
        error: null,
        ai_mode: "openai",
      },
    }, nextKey);
    expect(s.status).toBe("running");
    expect(s.stage).toBe("enrich");
    expect(s.counts).toMatchObject({ docs: 9, chunks: 22, enrichDone: 4, enrichTotal: 22 });
  });
});
