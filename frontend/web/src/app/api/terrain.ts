import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import { qk } from "./keys";
import type { ClaudeModel } from "./compileSettings";

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
  embedding_model?: "text-embedding-3-small" | "text-embedding-3-large" | null;
  llm_concurrency?: number | null;
}

export interface CompileStartResult {
  ok: boolean;
  ai_mode?: AiMode;
  reason?: string;
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
    mutationFn: (payload: CompileStartPayload = {}) =>
      apiFetch<CompileStartResult>("/api/terrain/build", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.terrainCurrent() });
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
