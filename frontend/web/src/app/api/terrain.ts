import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import { qk } from "./keys";
import type { ClaudeModel, EmbeddingModel } from "./compileSettings";
import {
  LOCAL_EMBEDDING_MODEL,
  OPENAI_EMBEDDING_MODEL,
  prepareLocalEmbeddings,
  waitForLocalEmbeddings,
  type LocalEmbeddings,
} from "./embeddings";
import { useLocalEmbeddingsPrompt } from "../lib/localEmbeddingsPromptStore";

// ─── Types (mirror backend src/api/routes_terrain.py + compile_orchestrator) ─

export type CompileStatus = "idle" | "running" | "complete" | "failed";
export type AiMode = "openai" | "anthropic" | "local" | "claude";

export interface CompileCounts {
  docs?: number;
  chunks?: number;
  /** Current enrich phase: "extract" (chunk analysis) → "embed". */
  enrich_phase?: "extract" | "embed";
  /** Done/total for the *current* enrich phase. */
  enrich_done?: number;
  enrich_total?: number;
  /** Per-phase done/total (present once enrich starts; used for the split bar). */
  enrich_extract_done?: number;
  enrich_extract_total?: number;
  enrich_embed_done?: number;
  enrich_embed_total?: number;
  derive_done?: number;
  derive_total?: number;
  /** EWMA-free lifetime enrich rate (chunks/sec) as of the last progress tick.
   *  Mirrored into the snapshot by the orchestrator so pollers (the TopBar ops
   *  pill) can compute an ETA without holding the SSE stream open. */
  rate_per_sec?: number;
}

export interface TerrainStats {
  regions: number;
  subRegionsTotal: number;
  tagsTotal: number;
  notes: number;
  sources: number;
  edges: number;
  deltas?: { tags: number; notes: number; edges: number };
}

export interface TerrainHighlights {
  godTags: string[];
  bridgeTags: string[];
  trendingTags: string[];
  isolatedTags: string[];
}

export interface BurningItem {
  id: string;
  type: "region" | "tag";
  label: string;
  attentionScore: number;
  attentionLevel: "none" | "low" | "medium" | "high" | "critical";
  signalCount: number;
}

export interface CompileSummary {
  run_id: string;
  ai_mode: AiMode;
  seconds: number;
  stats: TerrainStats;
}

export interface CompileCurrent {
  status: CompileStatus;
  started_at: number | null;
  finished_at: number | null;
  stage: string | null;
  counts: CompileCounts;
  summary: CompileSummary | null;
  error: string | null;
  ai_mode: AiMode | null;
  run_id: string | null;
}

export interface TerrainRun {
  id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  params: string;
  counts: string;
  error: string | null;
}

export interface TerrainReport {
  exists: boolean;
  generated_at: string | null;
  ai_mode: AiMode | null;
  seconds: number | null;
  stats: TerrainStats | null;
  highlights: TerrainHighlights | null;
  burning?: BurningItem[];
  /** Real LLM labels for highlighted tag ids (id → label). May be absent. */
  tag_labels?: Record<string, string>;
  compiler: { version: string; extractor: string; clusterer: string } | null;
  by_source: Record<string, number>;
  last_run: TerrainRun | null;
}

export interface CompileStartPayload {
  source?: string | null;
  ai_mode?: AiMode | null;
  /** Ignore the feature/embedding/name caches and recompute everything. */
  fresh?: boolean;
  // Per-run overrides. Omitted fields fall back to the saved compile-settings
  // defaults server-side (GET/PATCH /api/settings/compile).
  claude_extract_model?: ClaudeModel | null;
  claude_name_model?: ClaudeModel | null;
  openai_model?: string | null;
  embedding_model?: EmbeddingModel | null;
  llm_concurrency?: number | null;
}

export interface CompileStartResult {
  ok: boolean;
  ai_mode?: AiMode;
  reason?: string;
  /** Typed refusal. `openai_key_missing`: no OPENAI_API_KEY for embeddings;
   *  `local_model_missing`: the on-device model is selected but not downloaded;
   *  `claude_cli_missing`: CLI engine picked but no `claude` binary on the server. */
  code?: "openai_key_missing" | "local_model_missing" | "claude_cli_missing";
  /** True when compiling with the on-device embedder would resolve the refusal
   *  (Claude engines). False for the OpenAI engine, which needs the key anyway. */
  local_embeddings_eligible?: boolean;
  /** With `local_model_missing`: an OpenAI key is stored, so the dialog can
   *  offer OpenAI embeddings instead of the download. */
  openai_key_set?: boolean;
  /** Set when the saved engine is OpenAI (keyless) but a Claude engine is
   *  usable here: the dialog offers to switch to it + on-device embeddings. */
  suggested_ai_mode?: "claude" | "anthropic" | null;
  local_embeddings?: LocalEmbeddings | null;
  /** Set client-side when the user closed the local-embeddings dialog without
   *  choosing: not an error, so callers skip their error toast. */
  dismissed?: boolean;
}

/** Whether a refusal is one the local-embeddings consent dialog can resolve. */
export function needsLocalEmbeddingsConsent(res: CompileStartResult): boolean {
  return (
    !res.ok &&
    res.local_embeddings_eligible === true &&
    (res.code === "openai_key_missing" || res.code === "local_model_missing")
  );
}

async function postCompileStart(payload: CompileStartPayload): Promise<CompileStartResult> {
  return apiFetch<CompileStartResult>("/api/terrain/build", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** Start a compile; if the server refuses for want of an OpenAI key, ask the
 *  user (LocalEmbeddingsDialog) whether to run embeddings on this machine,
 *  download the model on a yes, and retry with it. Shared by every compile
 *  button via `useStartCompile`. */
export async function startCompileWithConsent(payload: CompileStartPayload): Promise<CompileStartResult> {
  const first = await postCompileStart(payload);
  if (!needsLocalEmbeddingsConsent(first)) return first;

  const decision = await useLocalEmbeddingsPrompt.getState().ask(payload, first);
  if (decision === "openai") {
    // The on-device default was never downloaded but a key is set: retry
    // with OpenAI embeddings. The server makes that the saved default.
    return postCompileStart({ ...payload, embedding_model: OPENAI_EMBEDDING_MODEL });
  }
  if (decision !== "local") {
    return { ok: false, dismissed: true, reason: first.reason, code: first.code };
  }
  // Download (idempotent when already present) and make it the default so
  // scheduled / auto compiles and Ask queries use the same embedding space.
  const aiMode = first.suggested_ai_mode ?? undefined;
  const started = await prepareLocalEmbeddings({ setDefault: true, aiMode });
  const settled = started.status === "ready" ? started : await waitForLocalEmbeddings();
  if (settled.status !== "ready") {
    return {
      ok: false,
      reason: settled.error
        ? `Couldn't download the on-device embedding model: ${settled.error}`
        : "Couldn't download the on-device embedding model.",
    };
  }
  return postCompileStart({
    ...payload,
    embedding_model: LOCAL_EMBEDDING_MODEL,
    ...(aiMode ? { ai_mode: aiMode } : {}),
  });
}

// ─── Hooks ──────────────────────────────────────────────────────────────

export function useTerrainCurrent(opts: { poll?: boolean } = {}) {
  return useQuery({
    queryKey: qk.terrainCurrent(),
    queryFn: () => apiFetch<CompileCurrent>("/api/terrain/current"),
    refetchInterval: (q) => {
      if (!opts.poll) return false;
      return q.state.data?.status === "running" ? 4_000 : false;
    },
    staleTime: 2_000,
  });
}

export function useTerrainReport() {
  return useQuery({
    queryKey: qk.terrainReport(),
    queryFn: () => apiFetch<TerrainReport>("/api/terrain/report"),
    staleTime: 30_000,
  });
}

export function useTerrainRuns() {
  return useQuery({
    queryKey: qk.terrainRuns(),
    queryFn: () => apiFetch<{ runs: TerrainRun[] }>("/api/terrain/runs"),
    staleTime: 30_000,
  });
}

export function useStartCompile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CompileStartPayload = {}) => startCompileWithConsent(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.terrainCurrent() });
      // The consent path may have saved a new embedding default.
      qc.invalidateQueries({ queryKey: ["compileSettings"] });
    },
  });
}

export function useCancelCompile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<{ ok: boolean }>("/api/terrain/cancel", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.terrainCurrent() });
    },
  });
}
