import { describe, expect, it } from "vitest";
import { CLAUDE_MODELS, findModel, modelLabel, normalizeModel } from "./models";

describe("ask model catalog", () => {
  it("maps legacy aliases saved by the old UI onto full model ids", () => {
    expect(normalizeModel("claude", "sonnet")).toBe("claude-sonnet-5");
    expect(normalizeModel("claude", "opus")).toBe("claude-opus-5");
    expect(normalizeModel("claude", "haiku")).toBe("claude-haiku-4-5");
    expect(normalizeModel("claude", "fable")).toBe("claude-fable-5-1");
  });

  it("passes unknown (custom) ids through untouched", () => {
    expect(normalizeModel("claude", "claude-opus-4-7")).toBe("claude-opus-4-7");
    expect(findModel("claude", "claude-opus-4-7")).toBeUndefined();
    expect(modelLabel("claude", "claude-opus-4-7")).toBe("claude-opus-4-7");
  });

  it("matches ids case-insensitively and labels them for the pill", () => {
    expect(modelLabel("claude", "Claude-Opus-5")).toBe("Claude Opus 5");
    expect(modelLabel("openai", "gpt-5.6-terra")).toBe("GPT-5.6 Terra");
  });

  it("offers the current Claude lineup including Fable and Opus 5", () => {
    const ids = CLAUDE_MODELS.map((m) => m.id);
    expect(ids).toEqual(
      expect.arrayContaining(["claude-fable-5-1", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]),
    );
    // No two rows share an alias — otherwise normalizeModel is ambiguous.
    const aliases = CLAUDE_MODELS.flatMap((m) => m.aliases ?? []);
    expect(new Set(aliases).size).toBe(aliases.length);
  });
});
