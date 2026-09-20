import { describe, expect, it } from "vitest";
import { isClaudeCliAvailable, isShuttingDown } from "../system";

describe("isClaudeCliAvailable", () => {
  it("is false on every spelling of Windows", () => {
    for (const p of ["win32", "Win32", "windows", "WIN64"]) {
      expect(isClaudeCliAvailable(p)).toBe(false);
    }
  });

  it("is true where the claude CLI ships", () => {
    expect(isClaudeCliAvailable("darwin")).toBe(true);
    expect(isClaudeCliAvailable("linux")).toBe(true);
    expect(isClaudeCliAvailable("freebsd13")).toBe(true);
  });

  it("shows everything while the platform is still unknown", () => {
    // /api/health hasn't answered yet — hiding an option from a Mac user for
    // a beat is worse than showing one Windows user a mode for a beat.
    expect(isClaudeCliAvailable(undefined)).toBe(true);
    expect(isClaudeCliAvailable(null)).toBe(true);
    expect(isClaudeCliAvailable("")).toBe(true);
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
