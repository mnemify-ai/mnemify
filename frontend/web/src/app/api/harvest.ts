import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import { qk } from "./keys";

// ─── Types ─────────────────────────────────────────────────────────────

export type HarvestStatus = "idle" | "running" | "complete" | "cancelled" | "failed";

/** Per-source terminal status, set by the backend's `source_complete` event
 *  (and carried on the `snapshot` for late joiners). Absent while a source is
 *  still listing/running — `HarvestPage` derives "listing"/"running" then. */
export type SourceStatus = "listing" | "running" | "complete" | "failed" | "cancelled";

export interface SourceProgress {
  done: number;
  failed: number;
  skipped: number;
  total: number;
  already_harvested: number;
  /** EWMA-smoothed docs/sec (see `smoothRate` in useHarvestStream). */
  rate: number | null;
  /** Bytes of raw content written this run (sum of new docs only). */
  bytes?: number;
  /** EWMA-smoothed bytes/sec; backs the bytes-weighted ETA for sources with
   *  highly variable per-doc cost (Notion). */
  bytes_rate?: number | null;
  /** Running average bytes-per-completed-doc; used to project remaining
   *  bytes from the remaining doc count. */
  avg_bytes_per_doc?: number | null;
  status?: SourceStatus;
}

export interface HarvestSummary {
  harvested: number;
  failed: number;
  skipped: number;
  seconds: number;
}

export interface HarvestCurrent {
  status: HarvestStatus;
  started_at: number | null;
  finished_at: number | null;
  sources: Record<string, SourceProgress>;
  summary: HarvestSummary | null;
}

export interface HarvestRun {
  id: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  sources: string[];
  docs_harvested: number;
  docs_failed: number;
}

export interface HarvestStartResult {
  ok: boolean;
  reason?: string | null;
  added: number;
  running: string[];
}

export interface HarvestStartPayload {
  sources?: string[] | null;
  force_full?: boolean;
  scope?: { source: string; space_id: string } | null;
  /** Per-source list of ids to harvest. When set for a source, only those ids
   *  are pulled — used by Manage Scope to auto-harvest just newly added items. */
  scope_override?: Record<string, string[]>;
}

// ─── Hooks ─────────────────────────────────────────────────────────────

export function useHarvestCurrent(opts: { poll?: boolean; idlePollMs?: number } = {}) {
  return useQuery({
    queryKey: qk.harvestCurrent(),
    queryFn: () => apiFetch<HarvestCurrent>("/api/harvest/current"),
    refetchInterval: (q) => {
      if (!opts.poll) return false;
      const data = q.state.data;
      // idlePollMs keeps a slow heartbeat while no run is active, so
      // scheduled harvests are noticed without any navigation.
      return data?.status === "running" ? 5_000 : (opts.idlePollMs ?? false);
    },
    staleTime: 2_000,
  });
}

export function useHarvestHistory() {
  return useQuery({
    queryKey: qk.harvestHistory(),
    queryFn: () => apiFetch<{ runs: HarvestRun[] }>("/api/harvest/history"),
    staleTime: 30_000,
  });
}

export function useStartHarvest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: HarvestStartPayload) =>
      apiFetch<HarvestStartResult>("/api/harvest", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.harvestCurrent() });
    },
  });
}

export function useCancelHarvest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ ok: boolean }>("/api/harvest/cancel", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.harvestCurrent() });
      qc.invalidateQueries({ queryKey: qk.harvestHistory() });
    },
  });
}

/** Wipe harvested data (raw bytes, normalized sidecars, manifest, log,
 *  compiled terrain) — sources + credentials are left intact. Refused while a
 *  harvest is running (server returns 409). */
export function useResetHarvest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ ok: boolean; removed: string[] }>("/api/harvest/reset", {
        method: "POST",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.harvestCurrent() });
      qc.invalidateQueries({ queryKey: qk.harvestHistory() });
      qc.invalidateQueries({ queryKey: qk.connections() });
      qc.invalidateQueries({ queryKey: qk.documents() });
      qc.invalidateQueries({ queryKey: qk.documentStats() });
      // Reset wipes the compiled map too — bust the map/terrain
      // caches so the Map tab flips to the empty state immediately
      // instead of showing the previously-rendered map.
      qc.invalidateQueries({ queryKey: qk.mapData() });
      qc.invalidateQueries({ queryKey: qk.terrainReport() });
    },
  });
}
