import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

export interface AuditEntry {
  ts: string;
  action: string;
  run?: string;
  source?: string;
  id?: string;
  title?: string;
  reason?: string;
  error?: string;
  parent?: string;
  file?: string;
  size?: number;
  mode?: string;
  stats?: Record<string, number>;
  // Open-ended — HarvestLogger may add fields.
  [key: string]: unknown;
}

export interface AuditLogResponse {
  entries: AuditEntry[];
  total: number;
  offset: number;
  limit: number;
  actions: string[];
}

export interface AuditQuery {
  offset?: number;
  limit?: number;
  action?: string;
  source?: string;
}

/**
 * Build the `/api/audit-log` path for a given query. Omits any field that is
 * `undefined`, `null`, or an empty string; appends a querystring only when at
 * least one filter is set. Extracted from {@link useAuditLog} so the
 * param-building logic can be unit-tested without TanStack Query.
 */
export function buildAuditLogPath(query: AuditQuery = {}): string {
  const params = new URLSearchParams();
  if (query.offset != null) params.set("offset", String(query.offset));
  if (query.limit != null) params.set("limit", String(query.limit));
  if (query.action) params.set("action", query.action);
  if (query.source) params.set("source", query.source);
  const qs = params.toString();
  return `/api/audit-log${qs ? `?${qs}` : ""}`;
}

export function useAuditLog(query: AuditQuery = {}) {
  const path = buildAuditLogPath(query);
  return useQuery<AuditLogResponse>({
    queryKey: ["audit-log", query],
    queryFn: () => apiFetch<AuditLogResponse>(path),
    staleTime: 10_000,
  });
}
