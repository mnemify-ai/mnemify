import { describe, expect, it } from "vitest";
import { resumeTargetFromRuns } from "./compileResume";
import type { TerrainRun } from "../api/terrain";

function run(over: Partial<TerrainRun>): TerrainRun {
  return {
    id: "r1",
    status: "failed",
    started_at: "2026-08-26T18:40:00",
    completed_at: "2026-08-26T18:41:00",
    params: JSON.stringify({ source: null, ai_mode: "openai", fresh: false }),
    counts: "{}",
    error: "server restarted",
    ...over,
  };
}

describe("resumeTargetFromRuns", () => {
  it("offers resume for a server-restart interruption, echoing run params", () => {
    const target = resumeTargetFromRuns([
      run({ params: JSON.stringify({ source: "notion", ai_mode: "claude" }) }),
    ]);
    expect(target).toEqual({ source: "notion", ai_mode: "claude", reason: "server restarted" });
  });

  it("offers resume for a cancelled run", () => {
    expect(resumeTargetFromRuns([run({ error: "cancelled" })])?.reason).toBe("cancelled");
  });

  it("offers resume when the run stopped on an LLM usage limit", () => {
    const target = resumeTargetFromRuns([
      run({
        error:
          "Usage limit reached — everything analyzed so far is saved; resume when your quota resets. (claude exited 1: usage limit)",
        params: JSON.stringify({ source: null, ai_mode: "anthropic" }),
      }),
    ]);
    expect(target).toEqual({ source: null, ai_mode: "anthropic", reason: "usage limit" });
  });

  it("ignores genuine failures — they would just fail again", () => {
    expect(resumeTargetFromRuns([run({ error: "bad month number 89; must be 1-12" })])).toBeNull();
  });

  it("only considers the most recent run", () => {
    const completed = run({ status: "completed", error: null });
    expect(resumeTargetFromRuns([completed, run({})])).toBeNull();
  });

  it("handles empty history and unreadable params", () => {
    expect(resumeTargetFromRuns([])).toBeNull();
    expect(resumeTargetFromRuns(undefined)).toBeNull();
    const target = resumeTargetFromRuns([run({ params: "not json" })]);
    expect(target).toEqual({ source: null, ai_mode: null, reason: "server restarted" });
  });
});
