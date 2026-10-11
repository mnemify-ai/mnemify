import { describe, expect, it } from "vitest";
import { applyAskEvent, extractCitationIds, toAskEvent } from "./askEvents";
import type { AgentStep, AskMessage } from "./types";

const empty: AskMessage = { id: "a", role: "assistant", text: "", pending: true };
const step = (id: string, status: AgentStep["status"], label = "Searching"): AgentStep => ({ id, tool: "retrieve_context", label, status });

describe("applyAskEvent", () => {
  it("accumulates text and tracks the [cN] markers it uses", () => {
    let m = applyAskEvent(empty, { kind: "delta", text: "Cut over Aug 18 [c2]" });
    m = applyAskEvent(m, { kind: "delta", text: " and closed [c1][c2]." });
    expect(m.text).toBe("Cut over Aug 18 [c2] and closed [c1][c2].");
    expect(m.usedCitationIds).toEqual(["c2", "c1"]);
    expect(m.pending).toBe(true);
  });

  it("upserts agent steps by id", () => {
    let m = applyAskEvent(empty, { kind: "agent_step", step: step("s1", "running") });
    m = applyAskEvent(m, { kind: "agent_step", step: step("s2", "running") });
    m = applyAskEvent(m, { kind: "agent_step", step: { ...step("s1", "done"), detail: "15 items" } });
    expect(m.steps?.map((s) => [s.id, s.status])).toEqual([["s1", "done"], ["s2", "running"]]);
  });

  it("lets citations_used override the streamed markers, and done/error settle it", () => {
    let m = applyAskEvent(empty, { kind: "delta", text: "x [c1] [c9]" });
    m = applyAskEvent(m, { kind: "citations_used", used: ["c1"], fallback: false });
    expect(m.usedCitationIds).toEqual(["c1"]);
    expect(applyAskEvent(m, { kind: "done" }).pending).toBe(false);
    const failed = applyAskEvent(m, { kind: "error", message: "boom" });
    expect(failed).toMatchObject({ error: "boom", pending: false });
  });
});

describe("toAskEvent", () => {
  it("parses the wire events the answer uses", () => {
    expect(toAskEvent("delta", { text: "hi" })).toEqual({ kind: "delta", text: "hi" });
    expect(toAskEvent("citations_used", { used: ["c1"] })).toEqual({ kind: "citations_used", used: ["c1"], fallback: false });
    expect(toAskEvent("status", { stage: "thinking" })).toEqual({ kind: "status", status: { stage: "thinking" } });
  });

  it("drops what it can't use", () => {
    expect(toAskEvent("thread", { thread_id: "t" })).toBeNull();
    expect(toAskEvent("retrieval_debug", {})).toBeNull();
    expect(toAskEvent("agent_step", { id: "s1" })).toBeNull(); // no label
    expect(toAskEvent("delta", {})).toBeNull();
  });
});

describe("extractCitationIds", () => {
  it("dedupes in first-appearance order", () => {
    expect(extractCitationIds("[c3] a [c1] b [c3]")).toEqual(["c3", "c1"]);
  });
});
