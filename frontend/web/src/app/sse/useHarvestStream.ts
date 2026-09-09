/**
 * EventSource wrapper for /api/harvest/stream.
 *
 * Backend emits unnamed messages (default 'message' event) with a `type`
 * discriminator in the JSON body — except for `ping` heartbeats which are
 * named events. We listen to `onmessage` only and switch on `type`.
 *
 * Lifecycle:
 *   enabled === true → opens EventSource; reconnects with exponential
 *                      backoff (1→2→4→8s, cap 30s) on error; resets
 *                      backoff on first successful message.
 *   enabled === false → closes and resets to idle.
 *
 * On `complete` or `cancelled`, invalidates ['connections'] +
 * ['harvest','current'] + ['harvest','history'] so the rest of the app
 * picks up post-run state.
 */

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiUrl } from "../api/client";
import { qk } from "../api/keys";
import {
  LOG_TAIL_BUFFER_LIMIT,
  RATE_EWMA_ALPHA,
  SSE_RECONNECT_BACKOFF_INITIAL_MS,
  SSE_RECONNECT_BACKOFF_MAX_MS,
} from "../lib/constants";
import type {
  HarvestStatus,
  SourceProgress,
  SourceStatus,
  HarvestSummary,
} from "../api/harvest";

const STREAM_URL = "/api/harvest/stream";

/** Exponentially-weighted moving average of the harvest rate.
 *  - `prev == null` → initialise with `sample` (don't blend up from 0).
 *  - callers must not pass a `null` sample — keep the previous value instead. */
export function smoothRate(prev: number | null, sample: number): number {
  if (prev == null) return sample;
  return RATE_EWMA_ALPHA * sample + (1 - RATE_EWMA_ALPHA) * prev;
}

/** Sum of every source's (already-smoothed) rate. Terminal sources carry
 *  `rate === 0`, warming-up ones `null` → both contribute 0, so this is the
 *  current aggregate throughput. */
function sumRates(perSource: Record<string, SourceProgress>): number {
  let total = 0;
  for (const p of Object.values(perSource)) total += p.rate ?? 0;
  return total;
}

/** Roll the smoothed aggregate rate forward off a fresh per-source map. When
 *  the aggregate momentarily reads 0 (every active source stalled, or all
 *  finished) we keep the last value so the total ETA shows the last known
 *  estimate rather than flickering to "—". Same EWMA the per-source rates use,
 *  so the headline ETA and the per-source ETAs glide on the same principle. */
function nextTotalRate(prev: number | null, perSource: Record<string, SourceProgress>): number | null {
  const instant = sumRates(perSource);
  return instant > 0 ? smoothRate(prev, instant) : prev;
}

export interface StreamLogEntry {
  /** Unique frontend id; backend events don't carry one. */
  key: string;
  level: "info" | "error";
  source: string;
  docId: string;
  title: string;
  msg: string;
  ts: number;
}

export interface HarvestStreamState {
  status: HarvestStatus;
  perSource: Record<string, SourceProgress>;
  /** EWMA-smoothed sum of the per-source rates (docs/sec across all sources);
   *  null while warming up. The Harvest page derives the headline ETA from
   *  this so it doesn't step when a source finishes. */
  totalRate: number | null;
  summary: HarvestSummary | null;
  logs: StreamLogEntry[];
  error: string | null;
  /** True when the EventSource is connected (`readyState === 1`). */
  connected: boolean;
}

const initialState: HarvestStreamState = {
  status: "idle",
  perSource: {},
  totalRate: null,
  summary: null,
  logs: [],
  error: null,
  connected: false,
};

interface BackendSnapshotEvent {
  type: "snapshot";
  state: {
    status: HarvestStatus;
    sources: Record<string, SourceProgress>;
    summary: HarvestSummary | null;
  };
}

interface BackendProgressEvent {
  type: "progress";
  source: string;
  done: number;
  /** Cache-hit and failure counters carried on every per-doc progress frame
   *  so the bar (which is (done + skipped + failed) / total) advances during
   *  cache-heavy re-harvests too. Optional for back-compat with the listing
   *  frame, which only carries done/total. */
  skipped?: number;
  failed?: number;
  total: number;
  /** Present on the listing-phase + source_complete frames; omitted on the
   *  per-doc progress frames. */
  already_harvested?: number;
  rate_per_sec: number | null;
  /** Per-doc bytes/sec from the backend's _BytesRate. Optional — older
   *  backends and the listing-phase frame omit it. */
  bytes_per_sec?: number | null;
  /** Running mean of bytes-per-completed-doc; combined with bytes_per_sec
   *  this gives the bytes-weighted ETA used for Notion. */
  avg_bytes_per_doc?: number | null;
}

interface BackendLogEvent {
  type: "log";
  level: "info";
  source: string;
  doc_id: string;
  title: string;
  msg: string;
  ts: number;
}

interface BackendErrorEvent {
  type: "error";
  level: "error";
  source: string;
  doc_id: string;
  title: string;
  msg: string;
  ts: number;
}

interface BackendSourceCompleteEvent {
  type: "source_complete";
  source: string;
  status: SourceStatus;
  done: number;
  failed: number;
  skipped: number;
  total: number;
  ts: number;
}

interface BackendCompleteEvent {
  type: "complete";
  summary: HarvestSummary;
  ts: number;
}

type BackendEvent =
  | BackendSnapshotEvent
  | BackendProgressEvent
  | BackendLogEvent
  | BackendErrorEvent
  | BackendSourceCompleteEvent
  | BackendCompleteEvent;

export function useHarvestStream(enabled: boolean): HarvestStreamState {
  const [state, setState] = useState<HarvestStreamState>(initialState);
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
        setState((s) => ({ ...s, connected: true, error: null }));
      };

      es.onmessage = (e) => {
        if (cancelled) return;
        // Reset backoff after a successful message.
        backoffRef.current = SSE_RECONNECT_BACKOFF_INITIAL_MS;

        let parsed: BackendEvent;
        try {
          parsed = JSON.parse(e.data) as BackendEvent;
        } catch {
          return;
        }
        setState((prev) => applyEvent(prev, parsed, () => {
          logKeyCounterRef.current += 1;
          return String(logKeyCounterRef.current);
        }));

        if (parsed.type === "complete") {
          queryClient.invalidateQueries({ queryKey: qk.connections() });
          queryClient.invalidateQueries({ queryKey: qk.harvestCurrent() });
          queryClient.invalidateQueries({ queryKey: qk.harvestHistory() });
        }
      };

      es.onerror = () => {
        if (cancelled) return;
        setState((s) => ({ ...s, connected: false }));
        es.close();
        esRef.current = null;
        // Backoff + retry
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

export function applyEvent(
  prev: HarvestStreamState,
  event: BackendEvent,
  nextKey: () => string,
): HarvestStreamState {
  const blankSource: SourceProgress = {
    done: 0,
    failed: 0,
    skipped: 0,
    total: 0,
    already_harvested: 0,
    rate: null,
  };

  switch (event.type) {
    case "snapshot": {
      const perSource = event.state.sources ?? {};
      return {
        ...prev,
        status: event.state.status,
        perSource,
        // Snapshot rates are the backend's raw values, not our EWMA — seed
        // the aggregate from them and let later progress events refine it.
        totalRate: nextTotalRate(prev.totalRate, perSource),
        summary: event.state.summary,
      };
    }

    case "progress": {
      const existing = prev.perSource[event.source] ?? blankSource;
      // `existing.rate` is the *previous smoothed* value (this reducer wrote
      // it last time), so reading it back keeps the function pure.
      // - rate_per_sec === null → backend still warming up: keep the previous
      //   smoothed value; the bar renders "calculating…".
      // - first non-null sample → seed the EWMA (don't blend from 0).
      const nextRate =
        event.rate_per_sec == null
          ? existing.rate
          : smoothRate(existing.rate, event.rate_per_sec);
      // Same EWMA treatment for bytes/sec so the bytes-weighted ETA glides
      // on the same principle as the docs/sec ETA.
      const nextBytesRate =
        event.bytes_per_sec == null
          ? existing.bytes_rate ?? null
          : smoothRate(existing.bytes_rate ?? null, event.bytes_per_sec);
      const perSource = {
        ...prev.perSource,
        [event.source]: {
          ...existing,
          done: event.done,
          // Cache-hit + failure counters are now carried on per-doc progress
          // frames too. Fall through to the existing value when absent (e.g.
          // the listing-phase frame) so we don't clobber it with undefined.
          skipped: event.skipped ?? existing.skipped,
          failed: event.failed ?? existing.failed,
          total: event.total,
          // Per-doc progress events from the backend omit this; keep the
          // value learned from the listing-phase event rather than clobbering.
          already_harvested: event.already_harvested ?? existing.already_harvested,
          rate: nextRate,
          bytes_rate: nextBytesRate,
          avg_bytes_per_doc:
            event.avg_bytes_per_doc ?? existing.avg_bytes_per_doc ?? null,
        },
      };
      return {
        ...prev,
        status: prev.status === "idle" ? "running" : prev.status,
        perSource,
        totalRate: nextTotalRate(prev.totalRate, perSource),
      };
    }

    case "source_complete": {
      const existing = prev.perSource[event.source] ?? blankSource;
      const perSource = {
        ...prev.perSource,
        [event.source]: {
          ...existing,
          done: event.done,
          failed: event.failed,
          skipped: event.skipped,
          total: event.total,
          rate: 0,
          status: event.status,
        },
      };
      return {
        ...prev,
        perSource,
        // A source dropping out steps the aggregate down — EWMA glides it
        // rather than letting the headline ETA jump.
        totalRate: nextTotalRate(prev.totalRate, perSource),
      };
    }

    case "log":
    case "error": {
      const entry: StreamLogEntry = {
        key: nextKey(),
        level: event.level,
        source: event.source,
        docId: event.doc_id,
        title: event.title,
        msg: event.msg,
        ts: event.ts,
      };
      const nextLogs = [entry, ...prev.logs].slice(0, LOG_TAIL_BUFFER_LIMIT);
      return { ...prev, logs: nextLogs };
    }

    case "complete":
      return {
        ...prev,
        status: "complete",
        summary: event.summary,
      };
  }
}
