import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { AiMode } from "./terrain";

/** A Claude model for a compile step: a full id ("claude-opus-5") or one of the
 *  legacy aliases ("opus" | "sonnet" | "haiku") still present in older configs.
 *  Pick from CLAUDE_MODELS in app/lib/modelCatalog. */
export type ClaudeModel = string;
export type EmbeddingModel = "text-embedding-3-small" | "text-embedding-3-large";
/** Reasoning effort for a compile step. "" = the provider's default. Applies
 *  to every LLM engine (OpenAI reasoning.effort, Claude API output_config.effort,
 *  Claude CLI --effort). Not part of any cache key. */
export type EffortLevel = "" | "low" | "medium" | "high";

/** Saved compile defaults — mirror of the backend `compile:` YAML block
 * (GET/PATCH /api/settings/compile). These seed each compile; the compile
 * dialog can override a subset per-run. */
export interface CompileSettings {
  ai_mode: AiMode;
  /** Model for the high-volume chunk feature-extraction step (default sonnet). */
  claude_extract_model: ClaudeModel;
  /** Model for the region/topic naming step (default opus). */
  claude_name_model: ClaudeModel;
  openai_model: string;
  embedding_model: EmbeddingModel;
  llm_concurrency: number;
  /** Chunks packed per extraction call (1–64). */
  extract_batch_size: number;
  /** Effort for the high-volume chunk analysis step (default "low"). */
  extract_effort: EffortLevel;
  /** Effort for region/topic naming + compiled notes (default "medium"). */
  name_effort: EffortLevel;
  claude_call_logging: boolean;
  default_source: string | null;
  /** When true, a successful harvest with changes kicks a compile automatically. */
  auto_compile_after_harvest: boolean;
  workspace: string;
  owner_name: string;
  owner_role: string;
}

export function useCompileSettings() {
  return useQuery<CompileSettings>({
    queryKey: ["compileSettings"],
    queryFn: () => apiFetch<CompileSettings>("/api/settings/compile"),
    staleTime: 10_000,
  });
}

export function useUpdateCompileSettings() {
  const qc = useQueryClient();
  return useMutation({
    // PATCH validates the full object server-side (all fields required), so
    // send the whole settings shape, not a partial.
    mutationFn: (body: CompileSettings) =>
      apiFetch<{ ok: boolean } & CompileSettings>("/api/settings/compile", {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["compileSettings"] }),
  });
}
