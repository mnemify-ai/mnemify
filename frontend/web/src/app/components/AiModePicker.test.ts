import { describe, expect, it } from "vitest";
import {
  compileOverridePayload,
  describeCompileMode,
  embeddingBackendOf,
  embeddingModelFor,
} from "./AiModePicker";

describe("compileOverridePayload", () => {
  it("sends both Claude model picks in claude mode", () => {
    expect(compileOverridePayload("claude", "haiku", "opus")).toEqual({
      ai_mode: "claude",
      claude_extract_model: "haiku",
      claude_name_model: "opus",
      embedding_model: undefined,
    });
  });

  it("omits Claude models outside claude mode so saved defaults win", () => {
    for (const mode of ["openai", "local"] as const) {
      expect(compileOverridePayload(mode, "haiku", "opus")).toEqual({
        ai_mode: mode,
        claude_extract_model: undefined,
        claude_name_model: undefined,
        embedding_model: undefined,
      });
    }
  });

  it("sends the embedding pick for every LLM engine, never for local heuristics", () => {
    for (const mode of ["openai", "claude", "anthropic"] as const) {
      expect(compileOverridePayload(mode, "sonnet", "opus", "text-embedding-3-large").embedding_model).toBe(
        "text-embedding-3-large",
      );
    }
    expect(compileOverridePayload("local", "sonnet", "opus", "bge-small-en-v1.5").embedding_model).toBeUndefined();
  });
});

describe("embedding backend switch", () => {
  it("maps models to the two-way switch", () => {
    expect(embeddingBackendOf("bge-small-en-v1.5")).toBe("local");
    expect(embeddingBackendOf("text-embedding-3-small")).toBe("openai");
  });

  it("keeps the saved OpenAI model when switching to OpenAI, else the default", () => {
    expect(embeddingModelFor("openai", "text-embedding-3-small")).toBe("text-embedding-3-small");
    expect(embeddingModelFor("openai", "bge-small-en-v1.5")).toBe("text-embedding-3-large");
    expect(embeddingModelFor("local", "text-embedding-3-large")).toBe("bge-small-en-v1.5");
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
