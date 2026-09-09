import { describe, expect, it } from "vitest";
import { compileOverridePayload, describeCompileMode } from "./AiModePicker";

describe("compileOverridePayload", () => {
  it("sends both Claude model picks in claude mode", () => {
    expect(compileOverridePayload("claude", "haiku", "opus")).toEqual({
      ai_mode: "claude",
      claude_extract_model: "haiku",
      claude_name_model: "opus",
    });
  });

  it("omits Claude models outside claude mode so saved defaults win", () => {
    for (const mode of ["openai", "local"] as const) {
      expect(compileOverridePayload(mode, "haiku", "opus")).toEqual({
        ai_mode: mode,
        claude_extract_model: undefined,
        claude_name_model: undefined,
      });
    }
  });
});

describe("describeCompileMode", () => {
  it("names the two Claude models when they're in play", () => {
    expect(
      describeCompileMode({
        ai_mode: "claude",
        claude_extract_model: "sonnet",
        claude_name_model: "opus",
      }),
    ).toBe("Claude CLI — chunks Claude Sonnet 5, naming Claude Opus 5");
  });

  it("labels full ids the same way and leaves unknown ids verbatim", () => {
    expect(
      describeCompileMode({
        ai_mode: "anthropic",
        claude_extract_model: "claude-haiku-4-5",
        claude_name_model: "claude-opus-4-7",
      }),
    ).toBe("Claude API — chunks Claude Haiku 4.5, naming claude-opus-4-7");
  });

  it("stays a bare engine name otherwise", () => {
    expect(
      describeCompileMode({
        ai_mode: "openai",
        claude_extract_model: "sonnet",
        claude_name_model: "opus",
      }),
    ).toBe("OpenAI");
    expect(
      describeCompileMode({
        ai_mode: "local",
        claude_extract_model: "sonnet",
        claude_name_model: "opus",
      }),
    ).toBe("Local heuristics");
  });
});
