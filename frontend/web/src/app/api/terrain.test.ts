import { describe, expect, it } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { compileFinishedSince, markCompileStarted, type CompileCurrent } from "./terrain";
import type { ChangesResponse } from "./changes";
import { qk } from "./keys";

function seeded() {
  const qc = new QueryClient();
  qc.setQueryData<CompileCurrent>(qk.terrainCurrent(), {
    status: "complete",
    started_at: 1,
    finished_at: 2,
    stage: "complete",
    counts: {},
    summary: null,
    error: null,
    ai_mode: "openai",
    run_id: "terrain_old",
  });
  qc.setQueryData(qk.changes("last_compile"), {
    compile_running: false,
    harvest_running: false,
  } as unknown as ChangesResponse);
  return qc;
}

describe("markCompileStarted", () => {
  it("flips the terrain status and every changes payload to running", () => {
    const qc = seeded();
    markCompileStarted(qc, { ok: true, ai_mode: "openai" });

    expect(qc.getQueryData<CompileCurrent>(qk.terrainCurrent())?.status).toBe("running");
    expect(qc.getQueryData<ChangesResponse>(qk.changes("last_compile"))?.compile_running).toBe(true);
  });

  it("leaves the cache alone when the server refused", () => {
    const qc = seeded();
    markCompileStarted(qc, { ok: false, reason: "a harvest is in progress" });

    expect(qc.getQueryData<CompileCurrent>(qk.terrainCurrent())?.status).toBe("complete");
    expect(qc.getQueryData<ChangesResponse>(qk.changes("last_compile"))?.compile_running).toBe(false);
  });
});

describe("compileFinishedSince", () => {
  const at = (status: CompileCurrent["status"], finished_at: number | null): CompileCurrent => ({
    status,
    started_at: 1,
    finished_at,
    stage: null,
    counts: {},
    summary: null,
    error: null,
    ai_mode: null,
    run_id: null,
  });

  it("ignores the first snapshot", () => {
    expect(compileFinishedSince(undefined, at("complete", 10))).toBe(false);
  });

  it("fires on a new finished_at even if the run was never seen running", () => {
    // Auto-compile after harvest / a schedule: complete → complete.
    expect(compileFinishedSince(10, at("complete", 20))).toBe(true);
  });

  it("fires after a run this tab started", () => {
    // markCompileStarted clears finished_at to null.
    expect(compileFinishedSince(null, at("complete", 20))).toBe(true);
  });

  it("does not fire again for the same run", () => {
    expect(compileFinishedSince(20, at("complete", 20))).toBe(false);
  });

  it("does not fire for running or failed runs", () => {
    expect(compileFinishedSince(10, at("running", null))).toBe(false);
    expect(compileFinishedSince(10, at("failed", 20))).toBe(false);
  });
});
