import { describe, it, expect } from "vitest";
import { buildAuditLogPath } from "../audit";

describe("buildAuditLogPath", () => {
  it("omits the querystring entirely when no filters are set", () => {
    expect(buildAuditLogPath()).toBe("/api/audit-log");
    expect(buildAuditLogPath({})).toBe("/api/audit-log");
  });

  it("includes offset === 0 (it's a value, not a default)", () => {
    // Regression guard: an `if (query.offset)` check would silently drop 0
    // and break pagination-from-the-top.
    expect(buildAuditLogPath({ offset: 0 })).toBe("/api/audit-log?offset=0");
  });

  it("omits empty-string action/source filters", () => {
    expect(buildAuditLogPath({ action: "", source: "" })).toBe("/api/audit-log");
  });

  it("URL-encodes filter values", () => {
    const path = buildAuditLogPath({ action: "harvest start", source: "notion+obsidian" });
    expect(path).toContain("action=harvest+start");
    expect(path).toContain("source=notion%2Bobsidian");
  });

  it("composes all four params when provided", () => {
    const path = buildAuditLogPath({ offset: 20, limit: 50, action: "delete", source: "notion" });
    const qs = new URLSearchParams(path.split("?")[1]);
    expect(qs.get("offset")).toBe("20");
    expect(qs.get("limit")).toBe("50");
    expect(qs.get("action")).toBe("delete");
    expect(qs.get("source")).toBe("notion");
  });
});
