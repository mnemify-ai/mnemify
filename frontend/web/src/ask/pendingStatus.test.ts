import { describe, expect, it } from "vitest";
import { elapsedLabel, pendingLabel } from "./pendingStatus";

describe("pendingLabel", () => {
  it("names each server stage", () => {
    expect(pendingLabel({ stage: "understanding" }, 0)).toBe("Understanding your question…");
    expect(pendingLabel({ stage: "searching" }, 0)).toBe("Searching your notes…");
    expect(pendingLabel({ stage: "reading", count: 1 }, 0)).toBe("Reading 1 document…");
    expect(pendingLabel({ stage: "reading", count: 7 }, 12)).toBe("Reading 7 documents…");
    expect(pendingLabel({ stage: "reading", count: 0 }, 3)).toBe("Reading what I found…");
    expect(pendingLabel({ stage: "writing" }, 12)).toBe("Writing the answer…");
    expect(pendingLabel({ stage: "thinking" }, 0)).toBe("Thinking…");
  });

  it("falls back to citations when the server sends no stage", () => {
    expect(pendingLabel(undefined, 0)).toBe("Thinking…");
    expect(pendingLabel(undefined, 1)).toBe("Reading 1 source…");
    expect(pendingLabel({ stage: "some-future-stage" }, 7)).toBe("Reading 7 sources…");
  });
});

describe("elapsedLabel", () => {
  it("stays quiet for short waits", () => {
    expect(elapsedLabel(0)).toBe("");
    expect(elapsedLabel(4.9)).toBe("");
  });

  it("shows whole seconds once the wait drags", () => {
    expect(elapsedLabel(5)).toBe("· 5s");
    expect(elapsedLabel(12.7)).toBe("· 12s");
  });
});
