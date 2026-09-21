import { describe, expect, it } from "vitest";
import { useLocalEmbeddingsPrompt } from "./localEmbeddingsPromptStore";
import { needsLocalEmbeddingsConsent } from "../api/terrain";

const refusal = {
  ok: false,
  code: "openai_key_missing" as const,
  local_embeddings_eligible: true,
  reason: "no key",
};

describe("localEmbeddingsPromptStore", () => {
  it("parks the request until the dialog settles it", async () => {
    const store = useLocalEmbeddingsPrompt.getState();
    const decision = store.ask({ ai_mode: "claude" }, refusal);
    expect(useLocalEmbeddingsPrompt.getState().request?.payload).toEqual({ ai_mode: "claude" });
    useLocalEmbeddingsPrompt.getState().settle("local");
    expect(await decision).toBe("local");
    expect(useLocalEmbeddingsPrompt.getState().request).toBeNull();
  });

  it("answers a stacked second request with the same decision", async () => {
    const store = useLocalEmbeddingsPrompt.getState();
    const first = store.ask({}, refusal);
    const second = store.ask({ fresh: true }, refusal);
    useLocalEmbeddingsPrompt.getState().settle(null);
    expect(await first).toBeNull();
    expect(await second).toBeNull();
  });
});

describe("needsLocalEmbeddingsConsent", () => {
  it("only fires for eligible key/model refusals", () => {
    expect(needsLocalEmbeddingsConsent(refusal)).toBe(true);
    expect(needsLocalEmbeddingsConsent({ ...refusal, code: "local_model_missing" })).toBe(true);
    expect(needsLocalEmbeddingsConsent({ ...refusal, local_embeddings_eligible: false })).toBe(false);
    expect(needsLocalEmbeddingsConsent({ ok: false, reason: "a harvest is in progress" })).toBe(false);
    expect(needsLocalEmbeddingsConsent({ ok: true, ai_mode: "claude" })).toBe(false);
  });
});
