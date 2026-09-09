/**
 * The one list of pickable models, shared by every model chooser in the app:
 * Ask chat (Claude / OpenAI), compile via Claude CLI, compile via Claude API,
 * compile via OpenAI. `id` is what goes on the wire — the Claude Code CLI and
 * the Anthropic API both accept full ids, so we store those rather than the
 * short "sonnet"/"opus" aliases older configs used. `aliases` keeps those
 * legacy values (and quick typing) mapping onto the right row.
 */
export type ModelOption = {
  id: string;
  label: string;
  hint: string;
  aliases?: readonly string[];
};

export const CLAUDE_MODELS: readonly ModelOption[] = [
  {
    id: "claude-sonnet-5",
    label: "Claude Sonnet 5",
    hint: "Best balance of speed and intelligence. Lighter on rate limits.",
    aliases: ["sonnet"],
  },
  {
    id: "claude-opus-5",
    label: "Claude Opus 5",
    hint: "Recommended for most work — complex reasoning and agentic exploration.",
    aliases: ["opus"],
  },
  {
    id: "claude-fable-5-1",
    label: "Claude Fable 5.1",
    hint: "Most capable — demanding reasoning and long-horizon work. Slowest and priciest.",
    aliases: ["fable"],
  },
  {
    id: "claude-haiku-4-5",
    label: "Claude Haiku 4.5",
    hint: "Fastest and cheapest, with near-frontier intelligence.",
    aliases: ["haiku"],
  },
  {
    id: "claude-opus-4-8",
    label: "Claude Opus 4.8",
    hint: "Previous Opus generation — same price tier as Opus 5.",
  },
];

/** Current OpenAI lineup, ordered from balanced to fast to premium. Hints
 *  quote standard-tier list prices per 1M input/output tokens. */
export const OPENAI_MODELS: readonly ModelOption[] = [
  {
    id: "gpt-5.6-terra",
    label: "GPT-5.6 Terra",
    hint: "Balanced flagship — strong quality at mid price ($2 in / $12 out).",
  },
  {
    id: "gpt-5.6-sol",
    label: "GPT-5.6 Sol",
    hint: "Most capable of the 5.6 family ($4 in / $20 out).",
  },
  {
    id: "gpt-5.6-luna",
    label: "GPT-5.6 Luna",
    hint: "Fast and cheap ($0.20 in / $1.20 out). Good for high-volume work.",
  },
  { id: "gpt-5.5", label: "GPT-5.5", hint: "Previous flagship ($5 in / $30 out)." },
  {
    id: "gpt-5.5-pro",
    label: "GPT-5.5 Pro",
    hint: "Premium reasoning tier — slow and expensive ($30 in / $180 out).",
  },
  { id: "gpt-5.4", label: "GPT-5.4", hint: "Older flagship ($2.50 in / $15 out)." },
  { id: "gpt-5.4-mini", label: "GPT-5.4 mini", hint: "Small and quick ($0.75 in / $4.50 out)." },
  {
    id: "gpt-5.4-nano",
    label: "GPT-5.4 nano",
    hint: "Smallest and cheapest ($0.20 in / $1.25 out).",
  },
  {
    id: "gpt-5.4-pro",
    label: "GPT-5.4 Pro",
    hint: "Premium reasoning tier, previous generation ($30 in / $180 out).",
  },
];

/** Catalog row for a stored value, matching by id or legacy alias. */
export function findModelOption(
  options: readonly ModelOption[],
  model: string,
): ModelOption | undefined {
  const needle = model.trim().toLowerCase();
  return options.find((m) => m.id === needle || m.aliases?.includes(needle));
}

/** Human label for a stored value; falls back to the raw id for custom models. */
export function modelOptionLabel(options: readonly ModelOption[], model: string): string {
  return findModelOption(options, model)?.label ?? model;
}
