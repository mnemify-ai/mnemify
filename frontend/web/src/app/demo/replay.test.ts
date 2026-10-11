import { describe, expect, it } from "vitest";
import { chunkText, scheduleReplay } from "./replay";

const step = (id: string, status: string) => ({ id, tool: "retrieve_context", label: `Step ${id}`, status, node_ids: [] });

// Shaped like a real agentic recording: a minute of exploring, then text.
const recording = [
  { t: 10, event: "thread", data: { thread_id: "demo-q01" } },
  { t: 40, event: "status", data: { stage: "understanding" } },
  { t: 900, event: "agent_step", data: step("s1", "running") },
  { t: 15000, event: "agent_step", data: step("s1", "done") },
  { t: 15100, event: "citations", data: { citations: [{ citation_id: "c1" }] } },
  { t: 41000, event: "agent_step", data: step("s2", "done") },
  { t: 60000, event: "delta", data: { text: "The cut-over happened on Aug 18 [c1]. " } },
  { t: 60500, event: "delta", data: { text: "Two follow-ups are still open." } },
  { t: 61000, event: "citations_used", data: { used: ["c1"], fallback: false } },
  { t: 61010, event: "done", data: {} },
];

describe("chunkText", () => {
  it("keeps every character", () => {
    const text = "  Hello there, Maya — the  [c1] answer\nis here. ";
    expect(chunkText(text).join("")).toBe(text);
  });

  it("groups a couple of words per piece", () => {
    expect(chunkText("a b c d e f g")).toEqual(["a b ", "c d ", "e f ", "g"]);
    expect(chunkText("a b c d e f g", 3)).toEqual(["a b c ", "d e f ", "g"]);
  });
});

describe("scheduleReplay", () => {
  const plan = scheduleReplay(recording);

  it("drops events the answer doesn't use", () => {
    expect(plan.some((p) => (p.ev as { kind: string }).kind === "thread")).toBe(false);
  });

  it("keeps the recorded order and never goes back in time", () => {
    const kinds = plan.map((p) => p.ev.kind);
    expect(kinds[0]).toBe("status");
    expect(kinds.indexOf("citations")).toBeLessThan(kinds.indexOf("delta"));
    expect(kinds[kinds.length - 1]).toBe("done");
    for (let i = 1; i < plan.length; i++) expect(plan[i].atMs).toBeGreaterThanOrEqual(plan[i - 1].atMs);
  });

  it("shortens the exploring phase", () => {
    const firstDelta = plan.find((p) => p.ev.kind === "delta")!;
    expect(firstDelta.atMs).toBeLessThan(6_500);
  });

  it("streams text at a believable pace, not all at once", () => {
    const long = [
      { t: 0, event: "agent_step", data: step("s1", "done") },
      { t: 10, event: "delta", data: { text: "word ".repeat(600) } }, // 3,000 chars
      { t: 20, event: "done", data: {} },
    ];
    const p = scheduleReplay(long);
    const first = p.find((x) => x.ev.kind === "delta")!.atMs;
    const last = p[p.length - 1].atMs;
    const seconds = (last - first) / 1000;
    expect(3000 / seconds).toBeGreaterThan(100); // not sluggish
    expect(3000 / seconds).toBeLessThan(220); // not a wall of text
  });

  it("streams the same text", () => {
    const text = plan.map((p) => (p.ev.kind === "delta" ? p.ev.text : "")).join("");
    expect(text).toBe("The cut-over happened on Aug 18 [c1]. Two follow-ups are still open.");
  });

  it("keeps commentary between agent steps in the exploring phase", () => {
    const withCommentary = [
      { t: 0, event: "delta", data: { text: "Let me look. " } },
      { t: 30000, event: "agent_step", data: step("s1", "done") },
      { t: 60000, event: "delta", data: { text: "Answer." } },
      { t: 60001, event: "done", data: {} },
    ];
    const p = scheduleReplay(withCommentary);
    const stepAt = p.find((x) => x.ev.kind === "agent_step")!.atMs;
    expect(stepAt).toBeLessThanOrEqual(5_000);
  });

  it("puts everything at t=0 for reduced motion", () => {
    const instant = scheduleReplay(recording, { reducedMotion: true });
    expect(instant.every((p) => p.atMs === 0)).toBe(true);
    expect(instant.map((p) => p.ev.kind)).toEqual(plan.map((p) => p.ev.kind));
  });
});
