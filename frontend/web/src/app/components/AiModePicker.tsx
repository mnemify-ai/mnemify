import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ClaudeModelSelectors } from "./ClaudeModelSelectors";
import { useCompileSettings, type ClaudeModel } from "../api/compileSettings";
import { CLAUDE_CLI_UNAVAILABLE_HINT, isClaudeCliAvailable, useHealth } from "../api/system";
import type { AiMode, CompileStartPayload } from "../api/terrain";
import { cn } from "../lib/cn";
import { CLAUDE_MODELS, modelOptionLabel } from "../lib/modelCatalog";

/**
 * The one AI-mode surface for compiles. Settings → AI & Models owns the saved
 * defaults; this is the point-of-use override, shown only where a compile is
 * actually about to start (the map's compile dialog and the Compile page's
 * first-run block). Anywhere else that merely *reports* how compiles run uses
 * {@link AiModeSummary}, which links back to Settings instead of offering a
 * third place to change the same value.
 */

const MODE_OPTIONS: ReadonlyArray<{ v: AiMode; label: string; desc: string }> = [
  {
    v: "openai",
    label: "OpenAI",
    desc: "OpenAI API — needs OPENAI_API_KEY (set in Settings → AI & Models)",
  },
  {
    v: "anthropic",
    label: "Claude API",
    desc: "Anthropic API — needs ANTHROPIC_API_KEY (set in Settings → AI & Models); works anywhere, incl. Windows",
  },
  {
    v: "claude",
    label: "Claude CLI",
    desc: "Your logged-in claude CLI (subscription) — local only, no API cost",
  },
  {
    v: "local",
    label: "Local heuristics",
    // The only mode that needs no key at all — every other mode still
    // embeds through OpenAI even when its naming engine is Claude.
    desc: "no LLM and no keys — near-instant, rougher clusters & names",
  },
];

const MODE_LABEL: Record<AiMode, string> = {
  openai: "OpenAI",
  anthropic: "Claude API",
  claude: "Claude CLI",
  local: "Local heuristics",
};

/** Modes that use the per-step Claude model split (CLI and API). */
const CLAUDE_MODEL_MODES: ReadonlyArray<AiMode> = ["claude", "anthropic"];

/** Per-run build-request fields for a mode + model selection. The per-step
 *  Claude model picks apply to both Claude engines (CLI + API); they're
 *  meaningless elsewhere, so they're omitted and the server falls back to the
 *  saved defaults. Pure — unit-tested. */
export function compileOverridePayload(
  aiMode: AiMode,
  extractModel: ClaudeModel,
  nameModel: ClaudeModel,
): Pick<CompileStartPayload, "ai_mode" | "claude_extract_model" | "claude_name_model"> {
  const usesClaudeModels = CLAUDE_MODEL_MODES.includes(aiMode);
  return {
    ai_mode: aiMode,
    claude_extract_model: usesClaudeModels ? extractModel : undefined,
    claude_name_model: usesClaudeModels ? nameModel : undefined,
  };
}

/** "Claude CLI — chunks Claude Sonnet 5, naming Claude Opus 5" / "OpenAI".
 *  Model ids (or legacy aliases) render as their catalog labels. Pure — unit-tested. */
export function describeCompileMode(settings: {
  ai_mode: AiMode;
  claude_extract_model: ClaudeModel;
  claude_name_model: ClaudeModel;
}): string {
  const base = MODE_LABEL[settings.ai_mode];
  if (!CLAUDE_MODEL_MODES.includes(settings.ai_mode)) return base;
  const extract = modelOptionLabel(CLAUDE_MODELS, settings.claude_extract_model);
  const name = modelOptionLabel(CLAUDE_MODELS, settings.claude_name_model);
  return `${base} — chunks ${extract}, naming ${name}`;
}

/** Per-run compile overrides, seeded once from the saved compile settings.
 *  Callers own no state of their own — they render {@link AiModePicker} with
 *  this object and send {@link CompileOverrides.payload} to the build API. */
export type CompileOverrides = {
  aiMode: AiMode;
  setAiMode: (v: AiMode) => void;
  extractModel: ClaudeModel;
  setExtractModel: (v: ClaudeModel) => void;
  nameModel: ClaudeModel;
  setNameModel: (v: ClaudeModel) => void;
  /** Body fields for POST /api/terrain/build. Claude model picks are sent
   *  only in claude mode; omitted fields fall back to the saved defaults. */
  payload: Pick<CompileStartPayload, "ai_mode" | "claude_extract_model" | "claude_name_model">;
};

export function useCompileOverrides(): CompileOverrides {
  const [aiMode, setAiMode] = useState<AiMode>("openai");
  const [extractModel, setExtractModel] = useState<ClaudeModel>("sonnet");
  const [nameModel, setNameModel] = useState<ClaudeModel>("opus");

  // Seed from the saved compile defaults exactly once — a background refetch
  // must never clobber a selection the user just made.
  const settings = useCompileSettings();
  const seededRef = useRef(false);
  useEffect(() => {
    if (!settings.data || seededRef.current) return;
    seededRef.current = true;
    setAiMode(settings.data.ai_mode);
    setExtractModel(settings.data.claude_extract_model);
    setNameModel(settings.data.claude_name_model);
  }, [settings.data]);

  return {
    aiMode,
    setAiMode,
    extractModel,
    setExtractModel,
    nameModel,
    setNameModel,
    payload: compileOverridePayload(aiMode, extractModel, nameModel),
  };
}

/** Interactive engine picker + the Claude model selectors it reveals. */
export function AiModePicker({
  overrides,
  compact,
}: {
  overrides: CompileOverrides;
  /** Caps the grid width where it sits inside a full-width page column. */
  compact?: boolean;
}) {
  const { aiMode, setAiMode } = overrides;
  // The claude CLI is macOS/Linux only. Disabled rather than hidden so a
  // Windows user sees *why* the mode they read about isn't there — and so a
  // config already saved as `claude` still renders its own button.
  const health = useHealth();
  const claudeCli = isClaudeCliAvailable(health.data?.platform);
  return (
    <div>
      <div className={cn("grid grid-cols-1 sm:grid-cols-2 gap-2", compact && "max-w-3xl")}>
        {MODE_OPTIONS.map((o) => {
          const blocked = o.v === "claude" && !claudeCli;
          return (
            <button
              key={o.v}
              type="button"
              disabled={blocked}
              onClick={() => setAiMode(o.v)}
              aria-pressed={aiMode === o.v}
              className={cn(
                "flex flex-col items-start gap-1 px-4 py-3 rounded-xl border text-left transition-colors",
                aiMode === o.v
                  ? "bg-ink text-cream border-ink"
                  : "bg-bone/40 text-ink border-hair hover:bg-bone",
                blocked && "opacity-disabled cursor-not-allowed hover:bg-bone/40",
              )}
            >
              <span className="font-serif text-base">Compile with: {o.label}</span>
              <span
                className={cn("font-sans text-xs", aiMode === o.v ? "text-cream/70" : "text-muted")}
              >
                {blocked ? CLAUDE_CLI_UNAVAILABLE_HINT : o.desc}
              </span>
            </button>
          );
        })}
      </div>
      {CLAUDE_MODEL_MODES.includes(aiMode) && (
        <ClaudeModelSelectors
          extractModel={overrides.extractModel}
          nameModel={overrides.nameModel}
          onExtractChange={overrides.setExtractModel}
          onNameChange={overrides.setNameModel}
        />
      )}
    </div>
  );
}

/**
 * Read-only "here's how compiles run" line for surfaces that report the
 * setting rather than change it. Deep-links to Settings → AI & Models, which
 * is the canonical editor.
 */
export function AiModeSummary({ className }: { className?: string }) {
  const { data, isLoading } = useCompileSettings();
  return (
    <p className={cn("font-sans text-sm text-muted", className)}>
      <span className="eyebrow mr-2">Compiling with</span>
      {isLoading || !data ? (
        <span className="text-muted">…</span>
      ) : (
        <span className="text-ink">{describeCompileMode(data)}</span>
      )}
      <Link to="/settings/ai" className="ml-2 text-magenta hover:underline">
        change →
      </Link>
    </p>
  );
}
