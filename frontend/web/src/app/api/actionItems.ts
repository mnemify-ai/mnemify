import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, ApiError } from "./client";
import { qk } from "./keys";

// ─── Types (mirror backend/src/api/routes_action_items.py) ────────────

/** `probably_abandoned`: still open, but the deadline passed more than
 * STALE_DEADLINE_DAYS (90) ago — filed at the bottom, never auto-resolved. */
export type ActionItemBucket =
  | "overdue"
  | "due_soon"
  | "upcoming"
  | "no_date"
  | "probably_abandoned";

/** One open todo signal flattened out of the compiled knowledge map. */
/** The user's own review verdict, stored server-side by signal id. */
export type ActionItemUserStatus = "unverified" | "confirmed" | "dismissed";

export interface ActionItem {
  id: string;
  title: string;
  summary: string;
  severity: number;
  status: string;
  owner: string | null;
  /** Resolved ISO deadline (YYYY-MM-DD), if the source text stated one. */
  due_date: string | null;
  /** The verbatim deadline phrase from the source ("by end of April"). */
  due_text: string | null;
  /** Days from `today` to the deadline (negative = overdue), null = no date. */
  days_until_due: number | null;
  bucket: ActionItemBucket;
  /** When the source note was last edited (ISO timestamp), if known. Shown
   * beside a stale deadline so the user can judge done vs. abandoned. */
  note_updated_at?: string | null;
  source_note_ids: string[];
  source_chunk_ids: string[];
  region_id: string | null;
  region_label: string | null;
  tag_id: string | null;
  tag_label: string | null;
  user_status: ActionItemUserStatus;
}

export interface ActionItemsResponse {
  generated_at: string | null;
  /** The server-side "today" the buckets were computed against (ISO date). */
  today: string;
  /** Set when the list was narrowed to one region's subtree. */
  region_id?: string | null;
  counts: Record<ActionItemBucket, number>;
  counts_by_status: Record<ActionItemUserStatus, number>;
  items: ActionItem[];
}

export interface ActionItemStatusResponse {
  signal_id: string;
  status: ActionItemUserStatus;
  updated_at: string;
}

/** `PATCH /api/action-items/{id}/status` — confirm or dismiss one item. The
 *  id is a content hash, so the verdict survives recompiles. Invalidates the
 *  global list and every region workspace (each embeds its own items). */
export function useSetActionItemStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: ActionItemUserStatus }) =>
      apiFetch<ActionItemStatusResponse>(
        `/api/action-items/${encodeURIComponent(id)}/status`,
        { method: "PATCH", body: JSON.stringify({ status }) },
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.actionItems() });
      void qc.invalidateQueries({ queryKey: qk.regions() });
    },
  });
}

// ─── Hooks ─────────────────────────────────────────────────────────────

/**
 * Open action items with read-time urgency buckets. 404 (no compile yet)
 * resolves to null rather than an error so callers can render an empty state.
 */
export function useActionItems() {
  return useQuery({
    queryKey: qk.actionItems(),
    queryFn: async (): Promise<ActionItemsResponse | null> => {
      try {
        return await apiFetch<ActionItemsResponse>("/api/action-items");
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
    staleTime: 60_000,
  });
}
