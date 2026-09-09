import type { AiMode, TerrainRun } from "../api/terrain";

export interface ResumeTarget {
  source: string | null;
  ai_mode: AiMode | null;
  reason: "server restarted" | "cancelled" | "usage limit";
}

// Interruptions are resumable. A run that failed on a real error would
// deterministically fail again, so it gets no resume affordance — except an
// LLM usage/rate limit: the compiler stops immediately, everything analyzed so
// far is cached, and re-running after the window resets only spends the rest.
// The backend prefixes those errors with USAGE_LIMIT_PREFIX (compiler.py
// RESUMABLE_ERROR_PREFIX).
const RESUMABLE_ERRORS = new Set(["server restarted", "cancelled"]);
export const USAGE_LIMIT_PREFIX = "usage limit reached";

function resumeReason(error: string): ResumeTarget["reason"] | null {
  if (RESUMABLE_ERRORS.has(error)) return error as "server restarted" | "cancelled";
  if (error.startsWith(USAGE_LIMIT_PREFIX)) return "usage limit";
  return null;
}

/**
 * If the most recent compile run was interrupted (server restart / cancel),
 * return the params to re-run it with. The pipeline caches features,
 * embeddings, and names in terrain.db as it goes, so re-running with
 * `fresh: false` skips finished work and only redoes in-flight losses.
 */
export function resumeTargetFromRuns(
  runs: TerrainRun[] | undefined | null,
): ResumeTarget | null {
  const latest = runs?.[0]; // recent_runs returns newest first
  if (!latest || latest.status !== "failed") return null;

  const error = (latest.error ?? "").trim().toLowerCase();
  const reason = resumeReason(error);
  if (!reason) return null;

  let source: string | null = null;
  let ai_mode: AiMode | null = null;
  try {
    const params = JSON.parse(latest.params || "{}");
    if (typeof params.source === "string" && params.source) source = params.source;
    if (
      params.ai_mode === "openai" ||
      params.ai_mode === "anthropic" ||
      params.ai_mode === "local" ||
      params.ai_mode === "claude"
    ) {
      ai_mode = params.ai_mode;
    }
  } catch {
    // Unreadable params → resume with server-side defaults.
  }

  return { source, ai_mode, reason };
}
