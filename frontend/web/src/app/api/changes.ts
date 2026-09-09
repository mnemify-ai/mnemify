import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import { qk } from "./keys";

// ─── Types ─────────────────────────────────────────────────────────────

export type ChangeKind = "new" | "updated" | "deleted";

/** One changed document since the boundary (default: last compile). */
export interface ChangeEntry {
  doc_id: string | null;
  source_id: string;
  source: string;
  title: string;
  change: ChangeKind;
  /** When the harvester recorded the change (trustworthy, local clock). */
  changed_at: string | null;
  /** When the source says the doc was last edited (display-only). */
  source_modified: string | null;
  /** Creator's display name. */
  author: string | null;
  /** Last editor's display name (may differ from author). */
  last_modified_by: string | null;
  url: string | null;
  space: string | null;
}

export interface ChangesSummary {
  new: number;
  updated: number;
  deleted: number;
  by_source: Record<string, { new: number; updated: number; deleted: number }>;
}

export interface ChangesResponse {
  boundary: { kind: "last_compile" | "timestamp"; ts: string | null };
  summary: ChangesSummary;
  changes: ChangeEntry[];
  /** True when the log may not cover the full window (rotated/wiped). */
  truncated: boolean;
  compile_running: boolean;
  harvest_running: boolean;
  /** completed_at of the most recent harvest run across all sources. */
  last_harvest_time: string | null;
  /** True when any source has an enabled harvest schedule. */
  schedule_enabled: boolean;
}

export function totalChanges(summary: ChangesSummary): number {
  return summary.new + summary.updated + summary.deleted;
}

// ─── Hooks ─────────────────────────────────────────────────────────────

/** Documents changed since `since` ("last_compile" or an ISO timestamp). */
export function useChanges(since = "last_compile", opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: qk.changes(since),
    queryFn: () =>
      apiFetch<ChangesResponse>(`/api/changes?since=${encodeURIComponent(since)}`),
    staleTime: 15_000,
    // Slow idle heartbeat (visible tabs only — refetchIntervalInBackground
    // defaults to false) so scheduled harvests surface without navigation.
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    enabled: opts.enabled ?? true,
  });
}
