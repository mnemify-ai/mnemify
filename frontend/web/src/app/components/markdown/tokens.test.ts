import { describe, expect, it } from "vitest";
import { headingCls, headingTag, inlineCodeCls } from "./tokens";

describe("headingTag", () => {
  it("starts documents at h2 — the page h1 is the document title", () => {
    expect(headingTag(1)).toBe("h2");
    expect(headingTag(2)).toBe("h3");
    expect(headingTag(3)).toBe("h4");
  });

  it("starts chat answers at h4 — a turn nests inside the dock's headings", () => {
    expect(headingTag(1, "chat")).toBe("h4");
    expect(headingTag(2, "chat")).toBe("h5");
    expect(headingTag(3, "chat")).toBe("h6");
  });

  it("never emits past h6 for deep or malformed levels", () => {
    expect(headingTag(6)).toBe("h6");
    expect(headingTag(99, "chat")).toBe("h6");
    expect(headingTag(0)).toBe("h2");
  });
});

describe("headingCls", () => {
  it("gives documents the full type scale", () => {
    expect(headingCls(1)).toContain("text-2xl");
    expect(headingCls(2)).toContain("text-xl");
    expect(headingCls(9)).toContain("text-base");
  });

  it("compresses chat to three steps that don't out-shout the UI", () => {
    expect(headingCls(1, "chat")).toContain("text-[15px]");
    expect(headingCls(2, "chat")).toContain("text-[13px]");
    expect(headingCls(3, "chat")).toContain("uppercase");
  });
});

describe("inlineCodeCls", () => {
  it("tints with bone on the doc surface and ink alpha in chat", () => {
    expect(inlineCodeCls()).toContain("bg-bone/60");
    expect(inlineCodeCls("chat")).toContain("bg-ink/[0.06]");
  });
});
