import { describe, expect, it } from "vitest";
import { describeAskFailure, extractCitationIds } from "./useAskStream";

describe("extractCitationIds", () => {
  it("dedupes in first-appearance order", () => {
    expect(extractCitationIds("Per [c3] and [c1], stable [c3].")).toEqual([
      "c3",
      "c1",
    ]);
  });

  it("returns empty for text without markers", () => {
    expect(extractCitationIds("no markers here")).toEqual([]);
    expect(extractCitationIds("")).toEqual([]);
  });

  it("ignores non-citation brackets", () => {
    expect(extractCitationIds("[note] [c12] [x1]")).toEqual(["c12"]);
  });
});

describe("describeAskFailure", () => {
  const noKey401 = JSON.stringify({
    detail: "no API key for openai — add it under Settings → AI & Models, or send Authorization: Bearer <key>.",
  });

  it("turns the server's 401 into a where-to-add-the-key message", () => {
    // The browser key is only an override; the server falls back to the key
    // saved in Settings, so only the server knows whether *no* key exists.
    expect(describeAskFailure(401, noKey401, "openai")).toMatch(
      /^Add your OpenAI API key in Settings → AI & Models/,
    );
    expect(describeAskFailure(401, noKey401, "claude")).toMatch(
      /^Add your Anthropic API key in Settings → AI & Models/,
    );
  });

  it("surfaces the backend's detail for other failures", () => {
    expect(
      describeAskFailure(409, JSON.stringify({ detail: "no compiled terrain — run /api/terrain/build first" }), "openai"),
    ).toBe("ask request failed: 409 — no compiled terrain — run /api/terrain/build first");
  });

  it("falls back to status plus body when the body isn't FastAPI JSON", () => {
    expect(describeAskFailure(502, "Bad Gateway", "openai")).toBe("ask request failed: 502 Bad Gateway");
    expect(describeAskFailure(500, "", "openai")).toBe("ask request failed: 500");
    expect(describeAskFailure(500, JSON.stringify({ detail: 42 }), "openai")).toBe(
      'ask request failed: 500 {"detail":42}',
    );
  });
});
