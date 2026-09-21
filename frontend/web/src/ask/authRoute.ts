import type { SecretRow } from "../app/api/secrets";
import { isAskProviderKeySet } from "../app/api/secrets";
import type { ClaudeStatus } from "./useClaudeStatus";
import { isClaudeReady } from "./useClaudeStatus";
import type { AskSettings } from "./types";
import { wireProvider } from "./types";

/**
 * How the *next* chat request will authenticate — the thing the composer
 * pill tells the user so "Claude" is never ambiguous between the local
 * Claude Code login and a metered Anthropic API key.
 *
 *  - `cli`        Claude engine, no browser key: rides the Claude Code login.
 *  - `browserKey` a key typed in Settings → AI & Models (this browser only).
 *  - `serverKey`  OpenAI with no browser key, but the server has one saved.
 *  - `none`       nothing to authenticate with; the request will be refused.
 *
 * Mirrors `wireProvider` — the Claude engine only becomes the BYOK
 * "anthropic" wire provider when a browser key is set, and a server-side
 * ANTHROPIC_API_KEY is never consulted on the CLI path.
 */
export type AuthRoute = "cli" | "browserKey" | "serverKey" | "none";

export function resolveAuthRoute(
  settings: AskSettings,
  secrets: SecretRow[] | undefined,
): AuthRoute {
  const wire = wireProvider(settings);
  if (wire === "claude") return "cli";
  if (wire === "anthropic") return "browserKey";
  if (settings.openaiKey.trim()) return "browserKey";
  return isAskProviderKeySet(secrets, "openai") ? "serverKey" : "none";
}

export type AuthRouteTone = "ok" | "warn" | "pending";

/** Short pill suffix + tone. `claudeStatus` only matters on the CLI route:
 *  undefined while the probe is in flight, null when it failed. */
export function describeAuthRoute(
  route: AuthRoute,
  claudeStatus: ClaudeStatus | null | undefined,
): { label: string; tone: AuthRouteTone; detail: string } {
  switch (route) {
    case "cli":
      if (claudeStatus === undefined) {
        return { label: "Claude Code", tone: "pending", detail: "Checking for Claude Code…" };
      }
      if (isClaudeReady(claudeStatus)) {
        return {
          label: "Claude Code",
          tone: "ok",
          detail: "Using this machine's Claude Code login — no API key needed.",
        };
      }
      return {
        label: "Claude Code",
        tone: "warn",
        detail:
          claudeStatus?.installed
            ? "Claude Code is installed but not logged in. Run `claude` in a terminal, or add an Anthropic API key in Settings."
            : "Claude Code not found. Install it and log in, or add an Anthropic API key in Settings.",
      };
    case "browserKey":
      return { label: "API key", tone: "ok", detail: "Using the API key saved in this browser." };
    case "serverKey":
      return { label: "API key", tone: "ok", detail: "Using the key saved on this machine (Settings → AI & Models)." };
    case "none":
      return { label: "No key", tone: "warn", detail: "Add an OpenAI API key in Settings to chat." };
  }
}
