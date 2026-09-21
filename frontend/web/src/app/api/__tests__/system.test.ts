import { describe, expect, it } from "vitest";
import { isClaudeCliAvailable, isShuttingDown } from "../system";

describe("isClaudeCliAvailable", () => {
  it("is false when the server found no claude binary on its PATH", () => {
    expect(isClaudeCliAvailable({ claude_cli: false })).toBe(false);
  });

  it("is true when the server found the binary — on any OS", () => {
    expect(isClaudeCliAvailable({ claude_cli: true })).toBe(true);
  });

  it("shows everything while health is still unknown or from an older server", () => {
    // /api/health hasn't answered yet — hiding an option for a beat is worse
    // than showing a mode that then fails with a clear "not installed" error.
    expect(isClaudeCliAvailable(undefined)).toBe(true);
    expect(isClaudeCliAvailable(null)).toBe(true);
    expect(isClaudeCliAvailable({})).toBe(true);
  });
});

describe("isShuttingDown", () => {
  it("is true only when the server says it is actually stopping", () => {
    expect(isShuttingDown({ ok: true, stopping: true })).toBe(true);
  });

  it("is false in --reload mode, where no server is registered to stop", () => {
    // 200 + stopping:false — the request succeeded but nothing went down, so
    // the "Mnemify has stopped" panel would be a lie.
    expect(isShuttingDown({ ok: true, stopping: false })).toBe(false);
  });

  it("is false for a missing or not-ok response", () => {
    expect(isShuttingDown(undefined)).toBe(false);
    expect(isShuttingDown(null)).toBe(false);
    expect(isShuttingDown({ ok: false, stopping: true })).toBe(false);
  });
});
