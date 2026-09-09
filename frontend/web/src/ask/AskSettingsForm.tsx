import { useEffect, useState } from "react";
import { apiFetch } from "../app/api/client";
import { cn } from "../app/lib/cn";
import { PROVIDER_LABELS } from "./ModelQuickSwitch";
import { MODEL_CATALOG } from "./models";
import { ModelSelect } from "../app/components/ModelSelect";
import { useAskSettingsStore } from "./askSettingsStore";
import type { AskEngine } from "./types";

/** Backend-side Claude Code detection (GET /api/ask/claude-status).
 *  `authenticated` is null when login state can't be read from disk. */
type ClaudeStatus = { installed: boolean; authenticated: boolean | null };

/**
 * The Ask engine/model/key form — the full settings surface for chat, shown
 * in Settings → AI & Models. Edits the shared `askSettingsStore`, so the
 * composer's quick-switch pill reflects changes live.
 *
 * Keys persist to localStorage; never sent anywhere except the `/api/ask`
 * request as `Authorization: Bearer <key>`.
 */
export function AskSettingsForm() {
  const settings = useAskSettingsStore((s) => s.settings);
  const onChange = useAskSettingsStore((s) => s.setSettings);
  const [claudeStatus, setClaudeStatus] = useState<ClaudeStatus | null>(null);

  // Probe for a local Claude Code install once, so the Claude option can say
  // whether the API key is actually needed.
  useEffect(() => {
    apiFetch<ClaudeStatus>("/api/ask/claude-status")
      .then(setClaudeStatus)
      .catch(() => setClaudeStatus(null));
  }, []);

  const claudeReady =
    claudeStatus?.installed === true && claudeStatus.authenticated !== false;

  const setProvider = (provider: AskEngine) => {
    onChange({ ...settings, provider, model: MODEL_CATALOG[provider][0].id });
  };

  return (
    <div className="space-y-4 font-sans text-sm text-ink">
      <fieldset className="space-y-2">
        <legend className="text-xs uppercase tracking-wide text-muted">
          Engine
        </legend>
        <div className="flex max-w-md gap-2">
          {(["claude", "openai"] as const).map((p) => (
            <label
              key={p}
              className={cn(
                "flex-1 cursor-pointer rounded-md border px-3 py-2 text-center transition-colors",
                settings.provider === p
                  ? "border-ink bg-ink/5"
                  : "border-hair hover:bg-bone/60",
              )}
            >
              <input
                type="radio"
                name="ask-provider"
                value={p}
                checked={settings.provider === p}
                onChange={() => setProvider(p)}
                className="sr-only"
              />
              <span>{PROVIDER_LABELS[p]}</span>
            </label>
          ))}
        </div>
        {settings.provider === "claude" ? (
          <div className="flex max-w-md items-start gap-2 rounded-md border border-hair bg-bone/40 px-3 py-2">
            <span
              aria-hidden
              className={cn(
                "mt-[3px] h-2 w-2 shrink-0 rounded-full",
                claudeStatus === null
                  ? "animate-pulse bg-muted/50"
                  : claudeReady
                    ? "bg-success"
                    : "bg-warning",
              )}
            />
            <p className="text-[11px] leading-relaxed text-muted">
              {claudeStatus === null ? (
                "Checking for Claude Code on this machine…"
              ) : claudeReady ? (
                <>
                  <span className="font-medium text-ink">Claude Code detected</span>{" "}
                  — chat works without an API key, on this machine's Claude
                  login. Adding a key below is optional and bills your
                  Anthropic API account instead.
                </>
              ) : claudeStatus.installed ? (
                <>
                  <span className="font-medium text-ink">
                    Claude Code is installed but not logged in.
                  </span>{" "}
                  Run <code>claude</code> in a terminal to log in, or add an
                  Anthropic API key below.
                </>
              ) : (
                <>
                  <span className="font-medium text-ink">
                    Claude Code not found on this machine.
                  </span>{" "}
                  Add an Anthropic API key below to chat, or install Claude
                  Code and log in.
                </>
              )}
            </p>
          </div>
        ) : null}
      </fieldset>

      <div className="max-w-md space-y-1">
        <label htmlFor="ask-model" className="block text-xs uppercase tracking-wide text-muted">
          Model
        </label>
        <ModelSelect
          id="ask-model"
          // Remount on engine switch so a half-typed custom id doesn't carry over.
          key={settings.provider}
          value={settings.model}
          options={MODEL_CATALOG[settings.provider]}
          onChange={(model) => onChange({ ...settings, model })}
          customPlaceholder={
            settings.provider === "claude" ? "e.g. claude-opus-4-7" : "e.g. gpt-5.6-terra"
          }
          customHint={
            settings.provider === "claude"
              ? "Any Anthropic model id, or a Claude Code alias like “opus”. Sent as-is."
              : "Any OpenAI chat model id. Sent as-is."
          }
        />
      </div>

      <label className="block max-w-md space-y-1">
        <span className="text-xs uppercase tracking-wide text-muted">
          {settings.provider === "claude"
            ? claudeStatus !== null && !claudeReady
              ? "Anthropic API key"
              : "Anthropic API key (optional)"
            : "OpenAI API key"}
        </span>
        <input
          type="password"
          value={
            settings.provider === "claude"
              ? settings.anthropicKey
              : settings.openaiKey
          }
          onChange={(e) => {
            const v = e.target.value;
            onChange(
              settings.provider === "claude"
                ? { ...settings, anthropicKey: v }
                : { ...settings, openaiKey: v },
            );
          }}
          placeholder={
            settings.provider === "claude" && claudeReady
              ? "Empty — use the local Claude Code login"
              : "sk-…"
          }
          autoComplete="off"
          className="w-full rounded-md border border-hair bg-cream px-3 py-1.5 outline-none focus:border-ink"
        />
        <span className="text-[11px] text-muted">
          Stored in this browser only, and used just to reach
          {settings.provider === "claude" ? " Anthropic" : " OpenAI"}. It never
          leaves this machine otherwise.
        </span>
      </label>
    </div>
  );
}
