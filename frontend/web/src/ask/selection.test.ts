import { describe, expect, it } from "vitest";
import { messageIdFor, normalizeSelection } from "./selection";

describe("normalizeSelection", () => {
  it("trims and rejects tiny selections", () => {
    expect(normalizeSelection("  a  ")).toBeNull();
    expect(normalizeSelection(" keep this ")).toBe("keep this");
    expect(normalizeSelection(null)).toBeNull();
  });
});

describe("messageIdFor", () => {
  it("walks up to the nearest message element inside the container", () => {
    const article = { parentNode: null, dataset: { messageId: "m1" } };
    const span = { parentNode: article, dataset: {} };
    expect(messageIdFor(span, () => true)).toBe("m1");
    expect(messageIdFor(span, () => false)).toBeNull();
    expect(messageIdFor(null, () => true)).toBeNull();
  });
});
