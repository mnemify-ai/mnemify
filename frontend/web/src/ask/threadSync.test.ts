import { describe, expect, it } from "vitest";
import { planImport, summaryToThread } from "./threadSync";
import type { AskThread } from "./askThreadStore";

const thread = (id: string, messages = 1): AskThread => ({
  id, title: id, createdAt: 1, updatedAt: 2, regionId: null,
  messages: Array.from({ length: messages }, (_, i) => ({ id: `${id}-${i}`, role: "user" as const, text: "q" })),
});

describe("planImport", () => {
  it("is a no-op once imported or when there is nothing to send", () => {
    expect(planImport([thread("a")], new Set(), true)).toBeNull();
    expect(planImport([thread("empty", 0)], new Set(), false)).toBeNull();
  });
  it("sends threads with messages plus dismissals", () => {
    const plan = planImport([thread("a"), thread("empty", 0)], new Set(["s1"]), false);
    expect(plan?.threads.map((t) => t.id)).toEqual(["a"]);
    expect(plan?.dismissed_action_item_ids).toEqual(["s1"]);
  });
});

describe("summaryToThread", () => {
  it("marks threads with messages as not yet loaded", () => {
    const t = summaryToThread({ id: "x", region_id: "r", region_name: "R", title: "T", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-02T00:00:00Z", message_count: 4 });
    expect(t.regionId).toBe("r");
    expect(t.messagesLoaded).toBe(false);
    expect(t.updatedAt).toBe(Date.parse("2026-01-02T00:00:00Z"));
    expect(summaryToThread({ id: "y", region_id: null, region_name: null, title: "", created_at: "", updated_at: "", message_count: 0 }).messagesLoaded).toBe(true);
  });
});
