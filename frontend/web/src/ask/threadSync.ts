// Server-backed conversations.
//
// `/api/ask` persists every exchange under its `thread_id` (workspace.db), so
// the browser's localStorage thread store is now a cache in front of the
// server list rather than the only copy. This module does the two things that
// need: a one-time import of what localStorage already held (so nothing is
// lost on the first run of this build), and a pull of server summaries into
// the store so a region's Activity tab can resume any conversation here.

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  deleteThreadOnServer,
  fetchThread,
  importWorkspace,
  useAllThreads,
  type ThreadSummary,
} from "../app/api/regions";
import { qk } from "../app/api/keys";
import { loadDismissed } from "../app/lib/actionItems";
import { useAskDockStore } from "./askDockStore";
import { useAskThreadStore, type AskThread } from "./askThreadStore";

export const IMPORT_FLAG_KEY = "mnemify.workspace.imported";

function flagSet(): boolean {
  try {
    return typeof localStorage !== "undefined" && localStorage.getItem(IMPORT_FLAG_KEY) === "1";
  } catch {
    return true; // no storage ⇒ nothing to import either
  }
}

function markImported(): void {
  try {
    localStorage.setItem(IMPORT_FLAG_KEY, "1");
  } catch {
    /* private mode — we'll simply retry next load; the server dedupes */
  }
}

/** Pure: what the one-time import should send, or null when nothing to do. */
export function planImport(
  threads: AskThread[],
  dismissed: Set<string>,
  alreadyImported: boolean,
): { threads: AskThread[]; dismissed_action_item_ids: string[] } | null {
  if (alreadyImported) return null;
  const withMessages = threads.filter((t) => t.messages.length > 0);
  if (withMessages.length === 0 && dismissed.size === 0) return null;
  return { threads: withMessages, dismissed_action_item_ids: [...dismissed] };
}

export function summaryToThread(s: ThreadSummary): AskThread {
  return {
    id: s.id,
    title: s.title,
    createdAt: Date.parse(s.created_at) || Date.now(),
    updatedAt: Date.parse(s.updated_at) || Date.now(),
    messages: [],
    regionId: s.region_id,
    messagesLoaded: s.message_count === 0,
  };
}

/** Fetch a thread's messages from the server when the store only holds its
 *  summary. No-op for threads the browser already has in full. */
export async function ensureThreadLoaded(id: string): Promise<void> {
  const t = useAskThreadStore.getState().threads.find((x) => x.id === id);
  if (t && t.messagesLoaded !== false) return;
  const detail = await fetchThread(id);
  useAskThreadStore.getState().upsertThread({
    ...summaryToThread(detail.thread),
    messages: detail.messages,
    messagesLoaded: true,
  });
}

/** Open a conversation in the dock — from a region's Activity tab or the
 *  thread switcher — loading it from the server first if needed. */
export async function resumeThread(id: string): Promise<void> {
  try {
    await ensureThreadLoaded(id);
  } catch {
    /* fall through — whatever the store has is still shown */
  }
  useAskThreadStore.getState().switchThread(id);
  useAskDockStore.getState().openDock();
}

/** Delete on the server, then locally. The local removal happens even if the
 *  server call fails (the thread may never have been persisted). */
export async function deleteThreadEverywhere(id: string): Promise<void> {
  try {
    await deleteThreadOnServer(id);
  } catch {
    /* 404 — nothing stored */
  }
  useAskThreadStore.getState().removeThread(id);
}

/** Mounted once in the shell (DashboardLayout) when a compiled map exists. */
export function useThreadSync(enabled: boolean): void {
  const qc = useQueryClient();

  useEffect(() => {
    if (!enabled) return;
    const plan = planImport(useAskThreadStore.getState().threads, loadDismissed(), flagSet());
    if (!plan) {
      if (!flagSet()) markImported();
      return;
    }
    void importWorkspace(plan)
      .then(() => {
        markImported();
        void qc.invalidateQueries({ queryKey: qk.threads() });
        void qc.invalidateQueries({ queryKey: qk.actionItems() });
      })
      .catch(() => undefined);
  }, [enabled, qc]);

  const { data } = useAllThreads({ enabled });
  useEffect(() => {
    if (!data) return;
    const upsert = useAskThreadStore.getState().upsertThread;
    for (const s of data.threads) upsert(summaryToThread(s));
  }, [data]);
}
