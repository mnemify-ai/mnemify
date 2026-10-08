import { create } from "zustand";
import { createJSONStorage, persist, type StateStorage } from "zustand/middleware";
import type { AskMessage } from "./types";

/**
 * Persisted conversation threads for Ask Mnemify.
 *
 * Messages used to live in `useState` inside `useAskStream`, which meant any
 * unmount (route change, reload) destroyed the conversation. This store is a
 * module-level singleton persisted to localStorage, so threads survive both
 * by construction. Streaming writes are keyed by thread id, so an in-flight
 * answer keeps landing in its own thread even if the user switches threads
 * mid-stream.
 *
 * Migration path: to move threads server-side later, add a `conversations`
 * table and swap the persist storage adapter for one backed by the API — the
 * shape here is already normalized (threads → messages).
 */

export type AskThread = {
  id: string;
  /** First user message, truncated — the thread's display name. */
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: AskMessage[];
  /** Region workspace this conversation belongs to (`/api/ask` scopes
   *  retrieval to it and files the thread under it). Null = whole map. */
  regionId: string | null;
  /** False for a server-side thread whose messages haven't been fetched yet
   *  (the sync only pulls summaries); `ensureThreadLoaded` fills them in. */
  messagesLoaded?: boolean;
};

const MAX_THREADS = 30;
const MAX_MESSAGES_PER_THREAD = 200;
const TITLE_MAX = 64;

type AskThreadState = {
  threads: AskThread[];
  activeThreadId: string | null;
  draft: string;
  /** Thread with an answer currently streaming, or null. Lives here (not in
   *  component state) because the dock unmounts when closed — an in-flight
   *  stream keeps writing to this store, so its status must outlive the UI. */
  streamingThreadId: string | null;

  setDraft: (draft: string) => void;
  setStreamingThread: (threadId: string | null) => void;
  /** Active thread id, creating an empty thread if none exists. */
  ensureActiveThread: () => string;
  newThread: () => void;
  /** Start (or re-point an empty active thread as) a conversation scoped to
   *  one region, and make it active. Returns the thread id. */
  newThreadForRegion: (regionId: string) => string;
  setThreadRegion: (threadId: string, regionId: string | null) => void;
  /** Merge a thread from the server: newer `updatedAt` wins, and a summary
   *  without messages never clobbers messages already held locally. */
  upsertThread: (thread: AskThread) => void;
  /** Drop a thread locally without touching the server. */
  removeThread: (id: string) => void;
  switchThread: (id: string) => void;
  deleteThread: (id: string) => void;
  /** Clear the active thread's messages ("Clear conversation"). */
  clearActiveThread: () => void;
  appendMessages: (threadId: string, messages: AskMessage[]) => void;
  patchMessage: (
    threadId: string,
    messageId: string,
    patch: (message: AskMessage) => AskMessage,
  ) => void;
};

export function newLocalId(): string {
  return Math.random().toString(36).slice(2, 12);
}

function threadTitle(messages: AskMessage[]): string {
  const first = messages.find((m) => m.role === "user")?.text.trim() ?? "";
  if (!first) return "New thread";
  return first.length > TITLE_MAX ? `${first.slice(0, TITLE_MAX - 1)}…` : first;
}

/** Newest-updated first, capped — the persistence (and switcher) order. */
function capThreads(threads: AskThread[]): AskThread[] {
  return [...threads]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, MAX_THREADS);
}

function touchThread(thread: AskThread, messages: AskMessage[]): AskThread {
  return {
    ...thread,
    messages: messages.slice(-MAX_MESSAGES_PER_THREAD),
    title: threadTitle(messages),
    updatedAt: Date.now(),
  };
}

/**
 * localStorage with quota fallback: if a write overflows (~5MB), drop the
 * oldest threads and retry with progressively fewer until it fits, rather
 * than silently persisting nothing from then on. All access is guarded so
 * the module also loads in non-DOM environments (vitest runs in node).
 */
const quotaAwareStorage: StateStorage = {
  getItem: (name) =>
    typeof localStorage === "undefined" ? null : localStorage.getItem(name),
  removeItem: (name) => {
    if (typeof localStorage !== "undefined") localStorage.removeItem(name);
  },
  setItem: (name, value) => {
    if (typeof localStorage === "undefined") return;
    try {
      localStorage.setItem(name, value);
      return;
    } catch {
      /* quota — prune below */
    }
    try {
      const parsed = JSON.parse(value) as {
        state?: { threads?: AskThread[] };
      };
      const threads = parsed.state?.threads;
      if (Array.isArray(threads) && parsed.state) {
        for (let keep = Math.min(threads.length - 1, 10); keep >= 1; keep = keep >> 1) {
          parsed.state.threads = threads.slice(0, keep); // already newest-first
          try {
            localStorage.setItem(name, JSON.stringify(parsed));
            return;
          } catch {
            /* still too big — halve again */
          }
        }
      }
      localStorage.removeItem(name);
    } catch {
      /* unparseable — give up quietly, chat still works unpersisted */
    }
  },
};

export const useAskThreadStore = create<AskThreadState>()(
  persist(
    (set, get) => ({
      threads: [],
      activeThreadId: null,
      draft: "",
      streamingThreadId: null,

      setDraft: (draft) => set({ draft }),
      setStreamingThread: (streamingThreadId) => set({ streamingThreadId }),

      ensureActiveThread: () => {
        const { threads, activeThreadId } = get();
        const active = threads.find((t) => t.id === activeThreadId);
        if (active) return active.id;
        const id = newLocalId();
        const now = Date.now();
        const thread: AskThread = {
          id,
          title: "New thread",
          createdAt: now,
          updatedAt: now,
          messages: [],
          regionId: null,
          messagesLoaded: true,
        };
        set({ threads: capThreads([thread, ...threads]), activeThreadId: id });
        return id;
      },

      newThreadForRegion: (regionId) => {
        const { threads, activeThreadId } = get();
        const active = threads.find((t) => t.id === activeThreadId);
        if (active && active.messages.length === 0) {
          set({
            threads: threads.map((t) => (t.id === active.id ? { ...t, regionId } : t)),
            draft: "",
          });
          return active.id;
        }
        const id = newLocalId();
        const now = Date.now();
        const thread: AskThread = {
          id,
          title: "New thread",
          createdAt: now,
          updatedAt: now,
          messages: [],
          regionId,
          messagesLoaded: true,
        };
        set({ threads: capThreads([thread, ...threads]), activeThreadId: id, draft: "" });
        return id;
      },

      setThreadRegion: (threadId, regionId) => {
        set({
          threads: get().threads.map((t) => (t.id === threadId ? { ...t, regionId } : t)),
        });
      },

      upsertThread: (incoming) => {
        const { threads } = get();
        const existing = threads.find((t) => t.id === incoming.id);
        if (!existing) {
          set({ threads: capThreads([incoming, ...threads]) });
          return;
        }
        const keepLocalMessages =
          incoming.messages.length === 0 && existing.messages.length > 0;
        const merged: AskThread = {
          ...existing,
          ...incoming,
          messages: keepLocalMessages ? existing.messages : incoming.messages,
          messagesLoaded: keepLocalMessages
            ? existing.messagesLoaded ?? true
            : incoming.messagesLoaded ?? existing.messagesLoaded,
          updatedAt: Math.max(existing.updatedAt, incoming.updatedAt),
          title: incoming.updatedAt >= existing.updatedAt ? incoming.title : existing.title,
        };
        set({ threads: capThreads(threads.map((t) => (t.id === merged.id ? merged : t))) });
      },

      removeThread: (id) => {
        const { threads, activeThreadId } = get();
        const remaining = threads.filter((t) => t.id !== id);
        set({
          threads: remaining,
          activeThreadId:
            activeThreadId === id ? (remaining[0]?.id ?? null) : activeThreadId,
        });
      },

      newThread: () => {
        const { threads, activeThreadId } = get();
        const active = threads.find((t) => t.id === activeThreadId);
        // An empty active thread already IS a new thread — just stay on it.
        if (active && active.messages.length === 0) return;
        set({ activeThreadId: null, draft: "" });
        get().ensureActiveThread();
      },

      switchThread: (id) => {
        if (get().threads.some((t) => t.id === id)) {
          set({ activeThreadId: id });
        }
      },

      deleteThread: (id) => {
        const { threads, activeThreadId } = get();
        const remaining = threads.filter((t) => t.id !== id);
        set({
          threads: remaining,
          activeThreadId:
            activeThreadId === id ? (remaining[0]?.id ?? null) : activeThreadId,
        });
      },

      clearActiveThread: () => {
        const { threads, activeThreadId } = get();
        set({
          threads: threads.map((t) =>
            t.id === activeThreadId
              ? { ...t, messages: [], title: "New thread", updatedAt: Date.now() }
              : t,
          ),
        });
      },

      appendMessages: (threadId, messages) => {
        set({
          threads: get().threads.map((t) =>
            t.id === threadId ? touchThread(t, [...t.messages, ...messages]) : t,
          ),
        });
      },

      patchMessage: (threadId, messageId, patch) => {
        set({
          threads: get().threads.map((t) =>
            t.id === threadId
              ? {
                  ...t,
                  messages: t.messages.map((m) => (m.id === messageId ? patch(m) : m)),
                }
              : t,
          ),
        });
      },
    }),
    {
      name: "mnemify.ask.threads.v1",
      storage: createJSONStorage(() => quotaAwareStorage),
      // v2 adds `regionId` (region-scoped conversations). Threads persisted
      // by v1 are whole-map conversations, so they migrate to `null`.
      version: 2,
      migrate: (persisted) => {
        const state = persisted as { threads?: AskThread[] };
        return {
          ...state,
          threads: (state.threads ?? []).map((t) => ({
            ...t,
            regionId: t.regionId ?? null,
            messagesLoaded: t.messagesLoaded ?? true,
          })),
        } as AskThreadState;
      },
      // A reload kills any in-flight request, so streaming status must never
      // be restored — it would strand the UI in a permanent "Stop" state.
      partialize: (s) => ({
        threads: s.threads,
        activeThreadId: s.activeThreadId,
        draft: s.draft,
      }),
      // A reload kills any in-flight stream: rehydrated messages must never
      // stay pending, or the UI shows a spinner forever.
      onRehydrateStorage: () => (state) => {
        if (!state) return;
        state.threads.forEach((t) => {
          t.messages.forEach((m) => {
            if (m.pending) m.pending = false;
            m.steps?.forEach((s) => {
              if (s.status === "running") s.status = "done";
            });
          });
        });
      },
    },
  ),
);

/** The active thread's messages (empty until the first send creates one). */
export function useActiveThreadMessages(): AskMessage[] {
  return useAskThreadStore(
    (s) => s.threads.find((t) => t.id === s.activeThreadId)?.messages ?? EMPTY_MESSAGES,
  );
}

const EMPTY_MESSAGES: AskMessage[] = [];
