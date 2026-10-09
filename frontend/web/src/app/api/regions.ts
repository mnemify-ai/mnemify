import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AskMessage, Citation } from "../../ask/types";
import { apiFetch, ApiError } from "./client";
import type { ActionItem, ActionItemBucket, ActionItemUserStatus } from "./actionItems";
import type { ChangeEntry } from "./changes";
import { qk } from "./keys";

// ─── Types (mirror backend/src/api/routes_regions.py) ─────────────────

export interface RegionCounts {
  notes?: number;
  sources?: number;
  tags?: number;
  subRegions?: number;
}

export interface RegionAttention {
  score: number | null;
  level: string | null;
}

/** One region in the `/api/regions` tree (nested through `children`). */
export interface RegionCard {
  id: string;
  name: string;
  level: number;
  parent_id: string | null;
  summary: string;
  color: string | null;
  counts: RegionCounts;
  note_count: number;
  attention: RegionAttention;
  signal_counts: { decision: number; open_question: number; todo: number; risk: number };
  memory_count: number;
  thread_count: number;
  last_visited_at: string | null;
  last_touched_at: string | null;
  children: RegionCard[];
}

export interface UnassignedRegion {
  region_key: string;
  region_name: string;
  memory_count: number;
  thread_count: number;
}

export interface RegionsIndexResponse {
  generated_at: string | null;
  regions: RegionCard[];
  unassigned: UnassignedRegion[];
}

export interface RegionPathEntry {
  id: string;
  name: string;
  level: number;
}

export interface RegionBrief {
  source: "compiled" | "refreshed";
  text: string;
  created_at: string | null;
  provider: string | null;
  model: string | null;
}

export type RegionSignalKind = "decision" | "open_question";

export interface RegionSignal {
  id: string;
  kind: RegionSignalKind;
  title: string;
  summary: string;
  severity: number;
  status: string;
  owner: string | null;
  due_date: string | null;
  due_text: string | null;
  created_or_updated_at: string | null;
  source_note_ids: string[];
  source_note_id: string | null;
  source_note_title: string | null;
  source_note_url: string | null;
  /** Harvest-manifest document id of the first source note, for the evidence
   *  drawer. Null when the manifest no longer holds the document. */
  source_doc_id: string | null;
  region_id: string | null;
  region_label: string | null;
  tag_id: string | null;
  tag_label: string | null;
}

export interface RegionActionItem extends ActionItem {
  source_doc_id: string | null;
  source_note_title: string | null;
}

export interface RegionSource {
  source: string;
  count: number;
}

export type MemoryKind = "answer" | "selection";

export interface MemoryOrigin {
  thread_id?: string;
  message_id?: string;
  span?: { start: number; end: number } | null;
  label?: string;
}

export interface MemoryItem {
  id: string;
  region_key: string;
  region_id: string | null;
  region_name: string | null;
  title: string;
  body: string;
  kind: MemoryKind;
  citations: Citation[];
  source_note_ids: string[];
  origin: MemoryOrigin;
  created_at: string;
  updated_at: string;
}

export interface RegionDetail {
  region: {
    id: string;
    name: string;
    level: number;
    summary: string;
    color: string | null;
    counts: RegionCounts;
    note_count: number;
    attention: RegionAttention;
    last_touched_at: string | null;
  };
  path: RegionPathEntry[];
  children: RegionCard[];
  brief: RegionBrief;
  decisions: { total: number; items: RegionSignal[] };
  open_questions: { total: number; items: RegionSignal[] };
  action_items: {
    counts: Record<ActionItemBucket, number>;
    counts_by_status: Record<ActionItemUserStatus, number>;
    items: RegionActionItem[];
  };
  sources: RegionSource[];
  memory_preview: MemoryItem[];
  memory_count: number;
  thread_count: number;
  map: {
    center: { x: number; y?: number; z: number } | null;
    radius: number | null;
    children: { id: string; name: string; center: unknown; radius: number | null }[];
  };
  last_visited_at: string | null;
  region_key: string | null;
  generated_at: string | null;
}

export interface RegionChange extends ChangeEntry {
  note_id: string;
  region_id: string | null;
  region_name: string | null;
}

export interface RegionChangesResponse {
  boundary: { kind: "last_compile" | "timestamp"; ts: string | null };
  changes: RegionChange[];
  /** Documents harvested after the compile that have no note on the map yet. */
  unmapped_count: number;
  truncated: boolean;
}

export interface MemoryGroup {
  region_id: string;
  region_name: string;
  is_self: boolean;
  path: string[];
  items: MemoryItem[];
}

export interface MemoryListResponse {
  groups: MemoryGroup[];
}

export interface MemoryCreate {
  title: string;
  body: string;
  kind: MemoryKind;
  citations?: Citation[];
  source_note_ids?: string[];
  origin?: MemoryOrigin;
}

export interface ThreadSummary {
  id: string;
  region_id: string | null;
  region_name: string | null;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ThreadDetail {
  thread: ThreadSummary;
  messages: AskMessage[];
}

export interface VisitResponse {
  previous_visited_at: string | null;
  visited_at: string;
  region_key: string;
}

export interface UnassignedDetail {
  region_key: string;
  region_name: string;
  status: "attached" | "orphaned";
  current_region_id: string | null;
  items: MemoryItem[];
  threads: ThreadSummary[];
}

export interface ImportResponse {
  threads_imported: number;
  threads_skipped: number;
  dismissals_imported: number;
  dismissals_skipped: number;
}

/** What `GET /api/regions/{id}` says when the id is stale. `moved_to` means
 *  the region survived a recompile under a new id; `region_key` means its
 *  memory and conversations are kept but no current region matches. */
export type StaleRegion =
  | { kind: "moved"; movedTo: string }
  | { kind: "orphaned"; regionKey: string; regionName: string }
  | { kind: "unknown" };

export function describeStaleRegion(err: unknown): StaleRegion | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | null;
  const detail = body && typeof body === "object" ? body.detail : null;
  if (err.status === 404) {
    if (detail && typeof detail === "object" && "moved_to" in detail) {
      return { kind: "moved", movedTo: String((detail as { moved_to: string }).moved_to) };
    }
    return { kind: "unknown" };
  }
  if (err.status === 410 && detail && typeof detail === "object" && "region_key" in detail) {
    const d = detail as { region_key: string; region_name?: string };
    return { kind: "orphaned", regionKey: d.region_key, regionName: d.region_name ?? "" };
  }
  return null;
}

// ─── Hooks ─────────────────────────────────────────────────────────────

const enc = encodeURIComponent;

export function useRegionsIndex() {
  return useQuery({
    queryKey: qk.regions(),
    queryFn: async (): Promise<RegionsIndexResponse | null> => {
      try {
        return await apiFetch<RegionsIndexResponse>("/api/regions");
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
    staleTime: 60_000,
  });
}

/** The workspace payload. A stale id rejects with an `ApiError` the layout
 *  turns into a redirect or an "Unassigned" page via `describeStaleRegion`. */
export function useRegion(id: string | null) {
  return useQuery({
    queryKey: qk.region(id ?? ""),
    queryFn: () => apiFetch<RegionDetail>(`/api/regions/${enc(id ?? "")}`),
    enabled: Boolean(id),
    staleTime: 30_000,
    retry: (count, err) => !(err instanceof ApiError) && count < 1,
  });
}

export function useRegionChanges(id: string | null, since: string, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: qk.regionChanges(id ?? "", since),
    queryFn: () =>
      apiFetch<RegionChangesResponse>(
        `/api/regions/${enc(id ?? "")}/changes?since=${enc(since)}`,
      ),
    enabled: Boolean(id) && (opts.enabled ?? true),
    staleTime: 30_000,
  });
}

export function useRegionMemory(id: string | null) {
  return useQuery({
    queryKey: qk.regionMemory(id ?? ""),
    queryFn: () => apiFetch<MemoryListResponse>(`/api/regions/${enc(id ?? "")}/memory`),
    enabled: Boolean(id),
    staleTime: 15_000,
  });
}

function invalidateRegionState(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: qk.regions() });
}

export function useCreateMemory(regionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: MemoryCreate) =>
      apiFetch<MemoryItem>(`/api/regions/${enc(regionId)}/memory`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => invalidateRegionState(qc),
  });
}

export function useUpdateMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...patch }: { id: string; title?: string; body?: string; region_id?: string }) =>
      apiFetch<MemoryItem>(`/api/regions/memory/${enc(id)}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    onSuccess: () => invalidateRegionState(qc),
  });
}

export function useDeleteMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<void>(`/api/regions/memory/${enc(id)}`, { method: "DELETE" }),
    onSuccess: () => invalidateRegionState(qc),
  });
}

export function useRegionThreads(id: string | null) {
  return useQuery({
    queryKey: qk.regionThreads(id ?? ""),
    queryFn: () =>
      apiFetch<{ threads: ThreadSummary[] }>(`/api/regions/${enc(id ?? "")}/threads`),
    enabled: Boolean(id),
    staleTime: 15_000,
  });
}

export function useAllThreads(opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: qk.threads(),
    queryFn: () => apiFetch<{ threads: ThreadSummary[] }>("/api/regions/threads"),
    enabled: opts.enabled ?? true,
    staleTime: 30_000,
  });
}

export function fetchThread(id: string): Promise<ThreadDetail> {
  return apiFetch<ThreadDetail>(`/api/regions/threads/${enc(id)}`);
}

export function deleteThreadOnServer(id: string): Promise<void> {
  return apiFetch<void>(`/api/regions/threads/${enc(id)}`, { method: "DELETE" });
}

export function useMoveThread() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, region_id }: { id: string; region_id: string | null }) =>
      apiFetch<ThreadSummary>(`/api/regions/threads/${enc(id)}`, {
        method: "PATCH",
        body: JSON.stringify({ region_id }),
      }),
    onSuccess: () => {
      invalidateRegionState(qc);
      void qc.invalidateQueries({ queryKey: qk.threads() });
    },
  });
}

export function recordVisit(id: string): Promise<VisitResponse> {
  return apiFetch<VisitResponse>(`/api/regions/${enc(id)}/visit`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function useUnassignedRegion(key: string | null) {
  return useQuery({
    queryKey: qk.unassignedRegion(key ?? ""),
    queryFn: () => apiFetch<UnassignedDetail>(`/api/regions/unassigned/${enc(key ?? "")}`),
    enabled: Boolean(key),
  });
}

export function useReassignUnassigned(key: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (region_id: string) =>
      apiFetch<{ region_id: string; moved_memory: number; moved_threads: number }>(
        `/api/regions/unassigned/${enc(key)}/reassign`,
        { method: "POST", body: JSON.stringify({ region_id }) },
      ),
    onSuccess: () => {
      invalidateRegionState(qc);
      void qc.invalidateQueries({ queryKey: qk.threads() });
    },
  });
}

export function importWorkspace(body: {
  threads: unknown[];
  dismissed_action_item_ids: string[];
}): Promise<ImportResponse> {
  return apiFetch<ImportResponse>("/api/workspace/import", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
