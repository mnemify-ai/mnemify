import { useQuery } from "@tanstack/react-query";
import { apiFetch, ApiError } from "./client";
import { qk } from "./keys";

// ─── Types (mirror backend/src/api/routes_action_items.py) ────────────

export type ActionItemBucket = "overdue" | "due_soon" | "upcoming" | "no_date";

/** One open todo signal flattened out of the compiled knowledge map. */
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
  source_note_ids: string[];
  source_chunk_ids: string[];
  region_id: string | null;
  region_label: string | null;
  tag_id: string | null;
  tag_label: string | null;
}

export interface ActionItemsResponse {
  generated_at: string | null;
  /** The server-side "today" the buckets were computed against (ISO date). */
  today: string;
  counts: Record<ActionItemBucket, number>;
  items: ActionItem[];
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
