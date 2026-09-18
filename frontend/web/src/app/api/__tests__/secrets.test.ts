import { describe, expect, it } from "vitest";
import {
  describeSecretStatus,
  findSecret,
  isAskProviderKeySet,
  secretNameForAskProvider,
  type SecretRow,
} from "../secrets";

function row(over: Partial<SecretRow> & { name: string }): SecretRow {
  return {
    label: over.name,
    kind: "api_key",
    provider: null,
    testable: false,
    set: false,
    hint: null,
    ...over,
  };
}

const ROWS: SecretRow[] = [
  row({ name: "OPENAI_API_KEY", provider: "openai", testable: true, set: true, hint: "…k3Fq" }),
  row({ name: "ANTHROPIC_API_KEY", provider: "anthropic", testable: true }),
  row({ name: "NOTION_TOKEN", kind: "token", provider: "notion", set: true, hint: "…wxyz" }),
];

describe("secretNameForAskProvider", () => {
  it("maps the OpenAI engine to the server's OpenAI key", () => {
    expect(secretNameForAskProvider("openai")).toBe("OPENAI_API_KEY");
  });

  it("maps the BYOK Anthropic wire provider to the Anthropic key", () => {
    expect(secretNameForAskProvider("anthropic")).toBe("ANTHROPIC_API_KEY");
  });

  it("gives the Claude-CLI engine no server key at all", () => {
    // The backend's `_PROVIDER_KEY_ENV` deliberately omits "claude": it runs
    // the local CLI on the user's subscription and never falls back to a
    // stored ANTHROPIC_API_KEY, so the form must not say one is in use.
    expect(secretNameForAskProvider("claude")).toBeNull();
  });

  it("returns null for an engine it doesn't know", () => {
    expect(secretNameForAskProvider("mistral")).toBeNull();
  });
});

describe("findSecret", () => {
  it("finds a row by name", () => {
    expect(findSecret(ROWS, "NOTION_TOKEN")?.hint).toBe("…wxyz");
  });

  it("is undefined-safe while the query is still loading", () => {
    expect(findSecret(undefined, "OPENAI_API_KEY")).toBeUndefined();
    expect(findSecret([], "OPENAI_API_KEY")).toBeUndefined();
  });
});

describe("isAskProviderKeySet", () => {
  it("is true only when the matching key is actually stored", () => {
    expect(isAskProviderKeySet(ROWS, "openai")).toBe(true);
    expect(isAskProviderKeySet(ROWS, "anthropic")).toBe(false);
  });

  it("is false for the Claude-CLI engine even with an Anthropic key stored", () => {
    const withAnthropic = ROWS.map((r) =>
      r.name === "ANTHROPIC_API_KEY" ? { ...r, set: true, hint: "…abcd" } : r,
    );
    expect(isAskProviderKeySet(withAnthropic, "anthropic")).toBe(true);
    expect(isAskProviderKeySet(withAnthropic, "claude")).toBe(false);
  });

  it("is false before the rows load, so the hint never flashes wrongly", () => {
    expect(isAskProviderKeySet(undefined, "openai")).toBe(false);
  });

  it("is false for an engine with no server-side key concept", () => {
    expect(isAskProviderKeySet(ROWS, "mistral")).toBe(false);
  });
});

describe("describeSecretStatus", () => {
  it("shows the masked hint when one is set", () => {
    expect(describeSecretStatus(findSecret(ROWS, "OPENAI_API_KEY"))).toBe("Set …k3Fq");
  });

  it("says Not set for an unset key", () => {
    expect(describeSecretStatus(findSecret(ROWS, "ANTHROPIC_API_KEY"))).toBe("Not set");
  });

  it("says Not set while the rows are still loading", () => {
    expect(describeSecretStatus(undefined)).toBe("Not set");
  });

  it("degrades to a bare Set if the server sends no hint", () => {
    // Possible for a very short value, where masking would reveal most of it.
    expect(describeSecretStatus(row({ name: "X", set: true }))).toBe("Set");
  });
});
