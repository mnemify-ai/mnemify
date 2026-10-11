// The sample workspace's data: static files exported by
// scripts/sample-data/export.py into public/demo, plus the little bit of
// state a visitor can change (todo verdicts, memory edits). That state lives
// in memory only: leaving the sample forgets it, and nothing reaches the
// backend or localStorage.

import type { ActionItem, ActionItemsResponse, ActionItemUserStatus } from "../api/actionItems";
import type {
  MemoryCreate,
  MemoryItem,
  MemoryListResponse,
  RegionChangesResponse,
  RegionDetail,
  ThreadSummary,
} from "../api/regions";
import type { AskStatus, Citation } from "../../ask/types";

export const SAMPLE_DATA_BASE = "/demo";

export type SampleQuestion = { id: string; label: string; question: string; regionId: string | null };

export type SampleManifest = {
  version: number;
  exportedAt: string;
  /** The day the server bucketed todos against (ISO date). */
  today: string;
  generatedAt: string | null;
  counts: Record<string, number>;
  questions: SampleQuestion[];
  docIdToNoteId: Record<string, string>;
};

/** One recorded `/api/ask` server-sent event, `t` ms after the request. */
export type SampleChatEvent =
  | { t: number; event: "citations"; data: { citations: Citation[] } }
  | { t: number; event: "delta"; data: { text: string } }
  | { t: number; event: "status"; data: AskStatus }
  | { t: number; event: "citations_used"; data: { used: string[]; fallback?: boolean } }
  | { t: number; event: string; data: unknown };

export type SampleChatRecord = SampleQuestion & {
  regionName: string | null;
  threadId: string;
  events: SampleChatEvent[];
};

export type SampleRegionFile = {
  detail: RegionDetail;
  changes: RegionChangesResponse;
  memory: MemoryListResponse;
  threads: { threads: ThreadSummary[] };
  action_items: ActionItemsResponse;
};

const STATUSES: ActionItemUserStatus[] = ["unverified", "confirmed", "dismissed"];

export class SampleStore {
  private files = new Map<string, Promise<unknown>>();
  private statuses = new Map<string, ActionItemUserStatus>();
  private memoryEdits = new Map<string, Partial<MemoryItem>>();
  private memoryDeleted = new Set<string>();
  private memoryAdded = new Map<string, MemoryItem[]>();
  private seq = 0;

  constructor(readonly base = SAMPLE_DATA_BASE) {}

  /** A fixture file, fetched once. Rejects with the HTTP status on a miss. */
  file<T>(rel: string): Promise<T> {
    let p = this.files.get(rel);
    if (!p) {
      p = fetch(`${this.base}/${rel}`).then((r) => {
        if (!r.ok) throw new SampleMissError(rel, r.status);
        return r.json();
      });
      // Don't pin a failure.
      p.catch(() => this.files.delete(rel));
      this.files.set(rel, p);
    }
    return p as Promise<T>;
  }

  // ── todo verdicts ──────────────────────────────────────────────────────

  setStatus(id: string, status: ActionItemUserStatus): void {
    this.statuses.set(id, status);
  }

  withStatuses<T extends { items: ActionItem[]; counts_by_status?: Record<ActionItemUserStatus, number> }>(res: T): T {
    if (this.statuses.size === 0) return res;
    const items = res.items.map((it) => {
      const s = this.statuses.get(it.id);
      return s ? { ...it, user_status: s } : it;
    });
    const counts = Object.fromEntries(STATUSES.map((s) => [s, 0])) as Record<ActionItemUserStatus, number>;
    for (const it of items) counts[it.user_status] = (counts[it.user_status] ?? 0) + 1;
    return { ...res, items, counts_by_status: counts };
  }

  // ── memory ─────────────────────────────────────────────────────────────

  addMemory(regionId: string, regionName: string | null, body: MemoryCreate, now: string): MemoryItem {
    this.seq += 1;
    const item: MemoryItem = {
      id: `sample-mem-${this.seq}`,
      region_key: `sample:${regionId}`,
      region_id: regionId,
      region_name: regionName,
      title: body.title,
      body: body.body,
      kind: body.kind,
      citations: body.citations ?? [],
      source_note_ids: body.source_note_ids ?? [],
      origin: body.origin ?? {},
      created_at: now,
      updated_at: now,
    };
    this.memoryAdded.set(regionId, [item, ...(this.memoryAdded.get(regionId) ?? [])]);
    return item;
  }

  editMemory(id: string, patch: Partial<MemoryItem>): void {
    this.memoryEdits.set(id, { ...this.memoryEdits.get(id), ...patch });
  }

  deleteMemory(id: string): void {
    this.memoryDeleted.add(id);
  }

  withMemoryEdits(list: MemoryListResponse, regionId: string): MemoryListResponse {
    const added = this.memoryAdded.get(regionId) ?? [];
    const groups = list.groups.map((g) => ({
      ...g,
      items: [...(g.is_self ? added : []), ...g.items]
        .filter((m) => !this.memoryDeleted.has(m.id))
        .map((m) => ({ ...m, ...this.memoryEdits.get(m.id) })),
    }));
    return { groups };
  }

  memoryPreview(items: MemoryItem[], regionId: string): MemoryItem[] {
    return [...(this.memoryAdded.get(regionId) ?? []), ...items]
      .filter((m) => !this.memoryDeleted.has(m.id))
      .map((m) => ({ ...m, ...this.memoryEdits.get(m.id) }));
  }
}

export class SampleMissError extends Error {
  constructor(readonly rel: string, readonly status: number) {
    super(`sample fixture ${rel}: HTTP ${status}`);
  }
}
