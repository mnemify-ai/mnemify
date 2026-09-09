/**
 * EventSource wrapper for /api/terrain/stream — the compile-progress stream.
 *
 * Mirrors useHarvestStream: per-stage events drive a `done/total` bar and an
 * EWMA-smoothed rate over the *uncached* enrich (LLM) calls → ETA on the same
 * principle as the harvest one. `local` mode flashes through every stage.
 */

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiUrl } from "../api/client";
import { qk } from "../api/keys";
import { smoothRate } from "./useHarvestStream";
import {
  LOG_TAIL_BUFFER_LIMIT,
  SSE_RECONNECT_BACKOFF_INITIAL_MS,
  SSE_RECONNECT_BACKOFF_MAX_MS,
} from "../lib/constants";
import type { AiMode, CompileStatus, CompileSummary, TerrainStats } from "../api/terrain";

const STREAM_URL = "/api/terrain/stream";

export interface CompileLogEntry {
  key: string;
  level: "info" | "error";
  stage: string;
  msg: string;
  ts: number;
}

export interface CompileCountsState {
  docs: number;
  chunks: number;
  /** Current enrich phase: "extract" (chunk analysis) → "embed". null pre-enrich. */
  enrichPhase: "extract" | "embed" | null;
  /** Done/total for the *current* enrich phase (drives ETA + the count label). */
  enrichDone: number;
  enrichTotal: number;
  /** Per-phase done/total — used to split the enrich progress segment. */
  enrichExtractDone: number;
  enrichExtractTotal: number;
  enrichEmbedDone: number;
  enrichEmbedTotal: number;
  deriveDone: number;
  deriveTotal: number;
}

export interface CompileStreamState {
  status: CompileStatus;
  stage: string | null;
  counts: CompileCountsState;
  /** EWMA-smoothed docs/sec over real (uncached) enrich calls; null while warming up. */
  rate: number | null;
  summary: CompileSummary | null;
  error: string | null;
  logs: CompileLogEntry[];
  connected: boolean;
}

const EMPTY_COUNTS: CompileCountsState = {
  docs: 0, chunks: 0, enrichPhase: null, enrichDone: 0, enrichTotal: 0,
  enrichExtractDone: 0, enrichExtractTotal: 0, enrichEmbedDone: 0, enrichEmbedTotal: 0,
  deriveDone: 0, deriveTotal: 0,
};

const initialState: CompileStreamState = {
  status: "idle",
  stage: null,
  counts: { ...EMPTY_COUNTS },
  rate: null,
  summary: null,
  error: null,
  logs: [],
  connected: false,
};

interface BackendSnapshotEvent {
  type: "snapshot";
  state: {
    status: CompileStatus;
    stage: string | null;
    counts: Record<string, number>;
    summary: CompileSummary | null;
    error: string | null;
    ai_mode: AiMode | null;
  };
}
interface BackendProgressEvent {
  type: "progress";
  stage: string;
  /** For enrich events: which sub-phase this tick belongs to. */
  phase?: "extract" | "embed";
  done?: number;
  total?: number;
  count?: number;
  cached?: boolean;
  rate_per_sec?: number | null;
  ts: number;
}
interface BackendLogEvent {
  type: "log";
  level: "info";
  stage?: string;
  msg: string;
  ts: number;
}
interface BackendErrorEvent {
  type: "error";
  level: "error";
  stage?: string;
  msg: string;
  ts: number;
}
interface BackendCompleteEvent {
  type: "complete";
  run_id: string;
  ai_mode: AiMode;
  seconds: number;
  stats: TerrainStats;
  ts: number;
}
interface BackendFailedEvent {
  type: "failed";
  error: string;
  ts: number;
}
type BackendEvent =
  | BackendSnapshotEvent
  | BackendProgressEvent
  | BackendLogEvent
  | BackendErrorEvent
  | BackendCompleteEvent
  | BackendFailedEvent;

export function useCompileStream(enabled: boolean): CompileStreamState {
  const [state, setState] = useState<CompileStreamState>(initialState);
  const queryClient = useQueryClient();
  const esRef = useRef<EventSource | null>(null);
  const backoffRef = useRef<number>(SSE_RECONNECT_BACKOFF_INITIAL_MS);
  const reconnectTimerRef = useRef<number | null>(null);
  const logKeyCounterRef = useRef<number>(0);

  useEffect(() => {
    if (!enabled) {
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      setState((s) => ({ ...s, connected: false }));
      return;
    }

    let cancelled = false;
    function connect() {
      if (cancelled) return;
      const es = new EventSource(apiUrl(STREAM_URL));
      esRef.current = es;

      es.onopen = () => {
        if (cancelled) return;
        setState((s) => ({ ...s, connected: true }));
      };

      es.onmessage = (e) => {
        if (cancelled) return;
        backoffRef.current = SSE_RECONNECT_BACKOFF_INITIAL_MS;
        let parsed: BackendEvent;
        try {
          parsed = JSON.parse(e.data) as BackendEvent;
        } catch {
          return;
        }
        setState((prev) =>
          applyCompileEvent(prev, parsed, () => {
            logKeyCounterRef.current += 1;
            return String(logKeyCounterRef.current);
          }),
        );
        if (parsed.type === "complete" || parsed.type === "failed") {
          queryClient.invalidateQueries({ queryKey: qk.terrainCurrent() });
          queryClient.invalidateQueries({ queryKey: qk.terrainReport() });
          queryClient.invalidateQueries({ queryKey: qk.terrainRuns() });
          queryClient.invalidateQueries({ queryKey: qk.documentStats() });
          queryClient.invalidateQueries({ queryKey: qk.mapData() });
        }
      };

      es.onerror = () => {
        if (cancelled) return;
        setState((s) => ({ ...s, connected: false }));
        es.close();
        esRef.current = null;
        const delay = Math.min(backoffRef.current, SSE_RECONNECT_BACKOFF_MAX_MS);
        reconnectTimerRef.current = window.setTimeout(() => {
          backoffRef.current = Math.min(backoffRef.current * 2, SSE_RECONNECT_BACKOFF_MAX_MS);
          connect();
        }, delay);
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };
  }, [enabled, queryClient]);

  return state;
}

export function applyCompileEvent(
  prev: CompileStreamState,
  event: BackendEvent,
  nextKey: () => string,
): CompileStreamState {
  switch (event.type) {
    case "snapshot": {
      const c = event.state.counts ?? {};
      // enrich_phase rides along in the counts object as a string, not a number.
      const phaseRaw = (c as Record<string, unknown>).enrich_phase;
      const enrichPhase = phaseRaw === "extract" || phaseRaw === "embed" ? phaseRaw : null;
      return {
        ...prev,
        status: event.state.status ?? prev.status,
        stage: event.state.stage ?? prev.stage,
        counts: {
          docs: c.docs ?? 0,
          chunks: c.chunks ?? 0,
          enrichPhase,
          enrichDone: c.enrich_done ?? 0,
          enrichTotal: c.enrich_total ?? 0,
          enrichExtractDone: c.enrich_extract_done ?? 0,
          enrichExtractTotal: c.enrich_extract_total ?? 0,
          enrichEmbedDone: c.enrich_embed_done ?? 0,
          enrichEmbedTotal: c.enrich_embed_total ?? 0,
          deriveDone: c.derive_done ?? 0,
          deriveTotal: c.derive_total ?? 0,
        },
        summary: event.state.summary ?? prev.summary,
        error: event.state.error ?? prev.error,
      };
    }

    case "progress": {
      const s = event.stage;
      let counts = prev.counts;
      let rate = prev.rate;
      if (s === "load") {
        counts = { ...counts, docs: event.count ?? counts.docs };
      } else if (s === "chunk") {
        const t = event.total ?? counts.chunks;
        counts = {
          ...counts,
          chunks: t,
          enrichTotal: t,
          enrichDone: 0,
          enrichPhase: null,
          enrichExtractTotal: t,
          enrichExtractDone: 0,
          enrichEmbedDone: 0,
          enrichEmbedTotal: 0,
        };
      } else if (s === "enrich") {
        const phase = event.phase ?? counts.enrichPhase;
        counts = {
          ...counts,
          enrichPhase: phase,
          enrichDone: event.done ?? counts.enrichDone,
          enrichTotal: event.total ?? counts.enrichTotal,
        };
        if (phase === "extract") {
          counts.enrichExtractDone = event.done ?? counts.enrichExtractDone;
          counts.enrichExtractTotal = event.total ?? counts.enrichExtractTotal;
        } else if (phase === "embed") {
          counts.enrichEmbedDone = event.done ?? counts.enrichEmbedDone;
          counts.enrichEmbedTotal = event.total ?? counts.enrichEmbedTotal;
        }
        // rate_per_sec is null on cached chunks (the fast path) → keep prev rate.
        if (event.rate_per_sec != null) rate = smoothRate(rate, event.rate_per_sec);
      } else if (s === "derive") {
        counts = {
          ...counts,
          deriveDone: event.done ?? counts.deriveDone,
          deriveTotal: event.total ?? counts.deriveTotal,
        };
      }
      return {
        ...prev,
        status: prev.status === "idle" ? "running" : prev.status,
        stage: s ?? prev.stage,
        counts,
        rate,
      };
    }

    case "log":
    case "error": {
      const entry: CompileLogEntry = {
        key: nextKey(),
        level: event.level,
        stage: event.stage ?? (event.type === "error" ? "error" : ""),
        msg: event.msg,
        ts: event.ts,
      };
      return { ...prev, logs: [entry, ...prev.logs].slice(0, LOG_TAIL_BUFFER_LIMIT) };
    }

    case "complete":
      return {
        ...prev,
        status: "complete",
        stage: "complete",
        summary: {
          run_id: event.run_id,
          ai_mode: event.ai_mode,
          seconds: event.seconds,
          stats: event.stats,
        },
      };

    case "failed":
      return { ...prev, status: "failed", stage: "failed", error: event.error };
  }
  return prev;
}
