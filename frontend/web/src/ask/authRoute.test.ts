import { describe, expect, it } from "vitest";
import { describeAuthRoute, resolveAuthRoute } from "./authRoute";
import { DEFAULT_SETTINGS } from "./types";
import type { SecretRow } from "../app/api/secrets";

const openaiSaved: SecretRow[] = [
  { name: "OPENAI_API_KEY", label: "OpenAI", kind: "api_key", provider: "openai", testable: true, set: true, hint: "…abcd" },
];
const anthropicSaved: SecretRow[] = [
  { name: "ANTHROPIC_API_KEY", label: "Anthropic", kind: "api_key", provider: "anthropic", testable: true, set: true, hint: "…abcd" },
];

describe("resolveAuthRoute", () => {
  it("claude engine without a browser key rides the CLI, even with a server key", () => {
    expect(resolveAuthRoute(DEFAULT_SETTINGS, anthropicSaved)).toBe("cli");
  });
  it("claude engine with a browser key is BYOK", () => {
    expect(resolveAuthRoute({ ...DEFAULT_SETTINGS, anthropicKey: "sk-x" }, undefined)).toBe("browserKey");
  });
  it("openai prefers the browser key, then the server key, then nothing", () => {
    const openai = { ...DEFAULT_SETTINGS, provider: "openai" as const, model: "gpt-5" };
    expect(resolveAuthRoute({ ...openai, openaiKey: "sk-x" }, undefined)).toBe("browserKey");
    expect(resolveAuthRoute(openai, openaiSaved)).toBe("serverKey");
    expect(resolveAuthRoute(openai, undefined)).toBe("none");
  });
});

describe("describeAuthRoute", () => {
  it("names the CLI and reflects its readiness", () => {
    expect(describeAuthRoute("cli", undefined).tone).toBe("pending");
    expect(describeAuthRoute("cli", { installed: true, authenticated: true })).toMatchObject({ label: "Claude Code", tone: "ok" });
    expect(describeAuthRoute("cli", { installed: true, authenticated: null }).tone).toBe("ok");
    expect(describeAuthRoute("cli", { installed: true, authenticated: false }).tone).toBe("warn");
    expect(describeAuthRoute("cli", { installed: false, authenticated: null }).tone).toBe("warn");
    expect(describeAuthRoute("cli", null).tone).toBe("warn");
  });
  it("labels keys as keys", () => {
    expect(describeAuthRoute("browserKey", undefined).label).toBe("API key");
    expect(describeAuthRoute("serverKey", undefined).label).toBe("API key");
    expect(describeAuthRoute("none", undefined).tone).toBe("warn");
  });
});
