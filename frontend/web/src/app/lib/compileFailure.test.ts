import { describe, expect, it } from "vitest";
import { compileFailureKey, shouldShowCompileFailure } from "./compileFailure";

const failed = { status: "failed" as const, run_id: "run-1", finished_at: 1700 };

describe("shouldShowCompileFailure", () => {
  it("shows on ordinary routes when the last compile failed", () => {
    expect(shouldShowCompileFailure(failed, null, "/")).toBe(true);
    expect(shouldShowCompileFailure(failed, null, "/settings/ai")).toBe(true);
  });

  it("stays quiet unless the status is failed", () => {
    for (const status of ["idle", "running", "complete"] as const) {
      expect(shouldShowCompileFailure({ ...failed, status }, null, "/")).toBe(false);
    }
    expect(shouldShowCompileFailure(undefined, null, "/")).toBe(false);
    expect(shouldShowCompileFailure(null, null, "/")).toBe(false);
  });

  it("does not double up on the compile report page, which shows the failure itself", () => {
    expect(shouldShowCompileFailure(failed, null, "/build/compile")).toBe(false);
  });

  it("honours a dismissal for that run only", () => {
    const key = compileFailureKey(failed);
    expect(shouldShowCompileFailure(failed, key, "/")).toBe(false);
    // The next failure is a different run → shows again.
    expect(shouldShowCompileFailure({ ...failed, run_id: "run-2" }, key, "/")).toBe(true);
  });

  it("keys a run without an id by its finish time", () => {
    expect(compileFailureKey({ run_id: null, finished_at: 42 })).toBe("42");
    expect(compileFailureKey({ run_id: null, finished_at: null })).toBe("failed");
  });
});
