import { describe, expect, it } from "vitest";
import { isClaudeCliAvailable } from "../system";

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
