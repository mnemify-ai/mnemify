import { describe, it, expect } from "vitest";
import { smoothRate, applyEvent, type HarvestStreamState } from "./useHarvestStream";

const EMPTY: HarvestStreamState = {
  status: "idle",
  perSource: {},
  totalRate: null,
  summary: null,
  logs: [],
  error: null,
  connected: false,
};

let keyN = 0;
const nextKey = () => String(++keyN);

function variance(xs: number[]): number {
  const m = xs.reduce((a, b) => a + b, 0) / xs.length;
  return xs.reduce((a, b) => a + (b - m) ** 2, 0) / xs.length;
}

describe("smoothRate", () => {
  it("seeds the EWMA with the first sample (no blend up from 0)", () => {
    expect(smoothRate(null, 5)).toBe(5);
  });

  it("is a fixed point at steady state", () => {
    expect(smoothRate(5, 5)).toBe(5);
  });

  it("decays gradually toward 0 rather than cliff-edging", () => {
    let r: number | null = 10;
    const trail: number[] = [];
    for (let i = 0; i < 20; i++) {
      r = smoothRate(r, 0);
      trail.push(r);
    }
    expect(trail[0]).toBeGreaterThan(0); // didn't drop straight to 0
    expect(trail[0]).toBeLessThan(10); // but did move
    expect(trail[19]).toBeLessThan(trail[0]); // monotone toward 0
    expect(trail[19]).toBeLessThan(0.5); // and well on its way
    // strictly decreasing
    for (let i = 1; i < trail.length; i++) expect(trail[i]).toBeLessThan(trail[i - 1]);
  });

  it("smooths an oscillating signal", () => {
    const raw = [2, 7, 2, 7, 2, 7, 2, 7, 2, 7];
    let r: number | null = null;
    const smoothed = raw.map((s) => (r = smoothRate(r, s)));
    expect(variance(smoothed)).toBeLessThan(variance(raw));
  });
});

describe("applyEvent reducer", () => {
  it("EWMA-smooths the per-source rate from progress events", () => {
    let s = applyEvent(EMPTY, { type: "progress", source: "notion", done: 1, total: 10, already_harvested: 0, rate_per_sec: 4 }, nextKey);
    expect(s.perSource.notion.rate).toBe(4); // first sample seeds
    s = applyEvent(s, { type: "progress", source: "notion", done: 2, total: 10, rate_per_sec: 0 }, nextKey);
    expect(s.perSource.notion.rate).toBeGreaterThan(0); // not slammed to 0
    expect(s.perSource.notion.rate!).toBeLessThan(4);
    expect(s.perSource.notion.done).toBe(2);
  });

  it("keeps the previous smoothed rate when the backend reports null (warming up)", () => {
    let s = applyEvent(EMPTY, { type: "progress", source: "notion", done: 1, total: 10, rate_per_sec: 3 }, nextKey);
    expect(s.perSource.notion.rate).toBe(3);
    s = applyEvent(s, { type: "progress", source: "notion", done: 1, total: 10, rate_per_sec: null }, nextKey);
    expect(s.perSource.notion.rate).toBe(3);
  });

  it("preserves already_harvested across per-doc progress frames that omit it", () => {
    let s = applyEvent(EMPTY, { type: "progress", source: "notion", done: 0, total: 10, already_harvested: 4, rate_per_sec: null }, nextKey);
    expect(s.perSource.notion.already_harvested).toBe(4);
    s = applyEvent(s, { type: "progress", source: "notion", done: 1, total: 10, rate_per_sec: 2 }, nextKey);
    expect(s.perSource.notion.already_harvested).toBe(4);
  });

  it("marks a source complete on source_complete", () => {
    let s = applyEvent(EMPTY, { type: "progress", source: "obsidian", done: 58, total: 58, already_harvested: 0, rate_per_sec: 25 }, nextKey);
    s = applyEvent(s, { type: "source_complete", source: "obsidian", status: "complete", done: 58, failed: 0, skipped: 0, total: 58, ts: 0 }, nextKey);
    expect(s.perSource.obsidian.status).toBe("complete");
    expect(s.perSource.obsidian.rate).toBe(0);
  });

  it("EWMA-smooths the aggregate rate so the headline ETA doesn't step when a source finishes", () => {
    let s = applyEvent(EMPTY, { type: "progress", source: "notion", done: 1, total: 100, already_harvested: 0, rate_per_sec: 2 }, nextKey);
    s = applyEvent(s, { type: "progress", source: "obsidian", done: 30, total: 58, already_harvested: 0, rate_per_sec: 25 }, nextKey);
    const before = s.totalRate!;
    expect(before).toBeGreaterThan(2); // obsidian's throughput pulled the aggregate up
    s = applyEvent(s, { type: "source_complete", source: "obsidian", status: "complete", done: 58, failed: 0, skipped: 0, total: 58, ts: 0 }, nextKey);
    // doesn't snap straight down to notion's 2/s — it glides
    expect(s.totalRate!).toBeLessThan(before);
    expect(s.totalRate!).toBeGreaterThan(2);
  });

  it("appends log entries with fresh keys, capped to the buffer size", () => {
    let s = EMPTY;
    for (let i = 0; i < 250; i++) {
      s = applyEvent(s, { type: "log", level: "info", source: "notion", doc_id: `d${i}`, title: `t${i}`, msg: "harvested", ts: i }, nextKey);
    }
    expect(s.logs.length).toBe(200);
    // newest first
    expect(s.logs[0].docId).toBe("d249");
    // all keys unique
    expect(new Set(s.logs.map((l) => l.key)).size).toBe(s.logs.length);
  });

  it("takes status + summary from a snapshot", () => {
    const s = applyEvent(EMPTY, {
      type: "snapshot",
      state: {
        status: "running",
        sources: { notion: { done: 3, failed: 0, skipped: 0, total: 10, already_harvested: 1, rate: 2, status: "running" } },
        summary: null,
      },
    }, nextKey);
    expect(s.status).toBe("running");
    expect(s.perSource.notion.done).toBe(3);
  });
});
