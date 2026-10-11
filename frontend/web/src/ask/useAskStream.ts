import { useCallback } from "react";
import { apiUrl, CLIENT_HEADER, CLIENT_NAME } from "../app/api/client";
import { newLocalId, useActiveThreadMessages, useAskThreadStore } from "./askThreadStore";
import type { AgentStep, AskMessage, AskSettings, AskStatus, Citation } from "./types";
import { activeKey, wireProvider } from "./types";
import { asOfWireDate, useMapTimelineStore } from "../app/lib/mapTimelineStore";
import { useMapHighlightStore } from "../app/lib/mapHighlightStore";
import { applyAskEvent, applyAskEventToMap, extractCitationIds } from "./askEvents";
import { queryClient } from "../app/lib/queryClient";
import { qk } from "../app/api/keys";

/**
 * The in-flight request's abort handle, module-level for the same reason
 * `streamingThreadId` lives in the store: the dock unmounts when closed, and
 * a component-local ref would strand the running stream with no way to stop
 * it. One at a time — `send` refuses to start a second.
 */
let activeAbort: AbortController | null = null;

/**
 * Hook that owns SSE streaming against `/api/ask`. Messages live in the
 * persisted `askThreadStore` (not local state), so conversations survive
 * unmounts, route changes, and reloads. Streamed updates are keyed by the
 * thread id captured at send time — switching threads mid-stream doesn't
 * misroute deltas.
 *
 * Uses `fetch` + a manual SSE line-reader instead of `EventSource` because
 * the latter cannot send custom headers (we need
 * `Authorization: Bearer <user_key>`).
 */
export function useAskStream(settings: AskSettings) {
  const messages = useActiveThreadMessages();
  const streamingThreadId = useAskThreadStore((s) => s.streamingThreadId);
  const activeThreadId = useAskThreadStore((s) => s.activeThreadId);
  // Only report streaming for the thread on screen — a background thread's
  // answer shouldn't disable the composer of the one you switched to.
  const isStreaming =
    streamingThreadId !== null && streamingThreadId === activeThreadId;

  const send = useCallback(
    async (query: string): Promise<void> => {
      if (!query.trim()) return;
      const store = useAskThreadStore.getState();
      // One request at a time: the dock can unmount mid-stream, so guard here
      // rather than relying on the composer being disabled.
      if (store.streamingThreadId !== null) return;
      const threadId = store.ensureActiveThread();
      const regionId =
        useAskThreadStore.getState().threads.find((t) => t.id === threadId)?.regionId ?? null;
      const patch = (
        messageId: string,
        fn: (m: AskMessage) => AskMessage,
      ) => useAskThreadStore.getState().patchMessage(threadId, messageId, fn);

      // No client-side "is a key set?" guard: the browser key is only an
      // override. `/api/ask` falls back to the key saved in Settings → AI &
      // Models, and answers 401 when neither exists — `describeAskFailure`
      // turns that into the "add your key" message below.
      const key = activeKey(settings);

      // "Ask as of": when the map's timeline is rewound, the question is
      // scoped to what existed on that date (backend ask_asof.py).
      const asOfMs = useMapTimelineStore.getState().asOf;
      const asOf = asOfMs === null ? undefined : asOfWireDate(asOfMs);
      const userMsg = mkMessage("user", query.trim(), asOf ? { asOf } : {});
      const assistantId = newLocalId();
      const placeholder: AskMessage = {
        id: assistantId,
        role: "assistant",
        text: "",
        pending: true,
        citations: [],
      };

      // History from the thread as it exists right now (pre-send).
      const history = (
        useAskThreadStore
          .getState()
          .threads.find((t) => t.id === threadId)?.messages ?? []
      )
        .filter((m) => !m.pending && !m.error)
        .map((m) => ({ role: m.role, content: m.text }));

      store.appendMessages(threadId, [userMsg, placeholder]);
      // A new question retires the previous answer's map highlight; the
      // fresh one lands with this answer's `citations` event.
      useMapHighlightStore.getState().clear();
      let lastCitations: Citation[] = [];

      store.setStreamingThread(threadId);
      const controller = new AbortController();
      activeAbort = controller;
      try {
        const response = await fetch(apiUrl("/api/ask"), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            [CLIENT_HEADER]: CLIENT_NAME,
            ...(key ? { Authorization: `Bearer ${key}` } : {}),
          },
          body: JSON.stringify({
            query,
            provider: wireProvider(settings),
            model: settings.model,
            history,
            ...(asOf ? { as_of: asOf } : {}),
            // The server files the exchange under this thread (workspace.db);
            // the browser id is reused so both sides agree on the thread.
            thread_id: threadId,
            ...(regionId ? { region_id: regionId } : {}),
          }),
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          const detail = await safeBody(response);
          throw new Error(
            describeAskFailure(response.status, detail, settings.provider),
          );
        }
        await consumeSseStream(response.body, {
          onThread: (current) => {
            // Region ids are content hashes that change on recompile; the
            // server followed the anchor history, so adopt its current id.
            if (regionId && current && current !== regionId) {
              useAskThreadStore.getState().setThreadRegion(threadId, current);
            }
          },
          onCitations: (citations) => {
            lastCitations = citations;
            const ev = { kind: "citations", citations } as const;
            patch(assistantId, (m) => applyAskEvent(m, ev));
            // Light the map with everything retrieval touched. The agentic
            // path re-sends citations cumulatively as tools register items,
            // so keep one token per answer: first arrival frames the camera,
            // later ones only widen the set.
            applyAskEventToMap(ev, query, lastCitations);
          },
          onDelta: (text) => {
            patch(assistantId, (m) => applyAskEvent(m, { kind: "delta", text }));
          },
          onStatus: (status) => {
            patch(assistantId, (m) => applyAskEvent(m, { kind: "status", status }));
          },
          onAgentStep: (step) => {
            // Mirror the agent's exploration onto the 3D map. Fire-and-forget:
            // the store self-expires, so a dock closed mid-answer leaves
            // nothing behind.
            const ev = { kind: "agent_step", step } as const;
            applyAskEventToMap(ev, query, lastCitations);
            patch(assistantId, (m) => applyAskEvent(m, ev));
          },
          onCitationsUsed: (used, fallback) => {
            const ev = { kind: "citations_used", used, fallback } as const;
            patch(assistantId, (m) => applyAskEvent(m, ev));
            // Narrow the map to what the answer actually leaned on.
            applyAskEventToMap(ev, query, lastCitations);
          },
          onError: (msg) => {
            patch(assistantId, (m) => applyAskEvent(m, { kind: "error", message: msg }));
          },
          onDone: () => {
            patch(assistantId, (m) => applyAskEvent(m, { kind: "done" }));
          },
        });
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") {
          // User hit Stop — keep the partial answer, no error banner.
          patch(assistantId, (m) => ({ ...m, pending: false }));
        } else {
          const msg = err instanceof Error ? err.message : String(err);
          patch(assistantId, (m) => ({ ...m, error: msg, pending: false }));
        }
      } finally {
        useAskThreadStore.getState().setStreamingThread(null);
        activeAbort = null;
        // The server just stored this exchange — region Activity tabs and the
        // thread list should pick it up without a reload.
        void queryClient.invalidateQueries({ queryKey: qk.threads() });
        if (regionId) void queryClient.invalidateQueries({ queryKey: qk.regions() });
      }
    },
    [settings],
  );

  const cancel = useCallback(() => {
    activeAbort?.abort();
  }, []);

  const reset = useCallback(() => {
    cancel();
    useAskThreadStore.getState().clearActiveThread();
  }, [cancel]);

  return { messages, isStreaming, send, cancel, reset };
}

// ── SSE parser ───────────────────────────────────────────────────────

type Handlers = {
  onThread: (regionId: string | null) => void;
  onCitations: (citations: Citation[]) => void;
  onDelta: (text: string) => void;
  onAgentStep: (step: AgentStep) => void;
  onStatus: (status: AskStatus) => void;
  onCitationsUsed: (used: string[], fallback: boolean) => void;
  onError: (msg: string) => void;
  onDone: () => void;
};

// Kept importable from here for existing callers.
export { extractCitationIds };

async function consumeSseStream(
  stream: ReadableStream<Uint8Array>,
  handlers: Handlers,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent: string | null = null;
  let currentData = "";

  const dispatch = () => {
    if (!currentEvent) return;
    if (!currentData) return;
    try {
      const payload = JSON.parse(currentData);
      if (currentEvent === "thread") {
        handlers.onThread(typeof payload?.region_id === "string" ? payload.region_id : null);
      } else if (currentEvent === "citations") {
        handlers.onCitations((payload?.citations as Citation[]) || []);
      } else if (currentEvent === "delta") {
        handlers.onDelta(payload?.text || "");
      } else if (currentEvent === "status") {
        if (typeof payload?.stage === "string") handlers.onStatus(payload as AskStatus);
      } else if (currentEvent === "agent_step") {
        if (payload?.id && payload?.label) {
          handlers.onAgentStep(payload as AgentStep);
        }
      } else if (currentEvent === "citations_used") {
        handlers.onCitationsUsed(
          (payload?.used as string[]) || [],
          Boolean(payload?.fallback),
        );
      } else if (currentEvent === "error") {
        handlers.onError(payload?.message || "stream error");
      } else if (currentEvent === "done") {
        handlers.onDone();
      }
    } catch {
      // ignore malformed event payloads — they're benign in v0.5.
    }
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nlIdx: number;
    while ((nlIdx = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, nlIdx).replace(/\r$/, "");
      buffer = buffer.slice(nlIdx + 1);
      if (line === "") {
        dispatch();
        currentEvent = null;
        currentData = "";
        continue;
      }
      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        currentData += line.slice(5).trim();
      }
    }
  }
  // Flush a trailing event (no terminating blank line on close).
  dispatch();
  handlers.onDone();
}

/**
 * The assistant-bubble error for a failed `/api/ask` request.
 *
 * A 401 means the server found no key for the provider — neither the
 * `Authorization` header nor the stored secret — so the user is told where to
 * add one rather than shown a raw status line. Everything else surfaces the
 * backend's `detail` when the body is FastAPI-style JSON, and the status plus
 * a body excerpt otherwise. Pure — unit-tested.
 */
export function describeAskFailure(
  status: number,
  body: string,
  provider: AskSettings["provider"],
): string {
  if (status === 401) {
    return provider === "openai"
      ? "Add your OpenAI API key in Settings → AI & Models (or in this browser under Chat) to start."
      : "Add your Anthropic API key in Settings → AI & Models (or in this browser under Chat) to start.";
  }
  const detail = extractDetail(body);
  return detail
    ? `ask request failed: ${status} — ${detail}`
    : `ask request failed: ${status} ${body}`.trimEnd();
}

function extractDetail(body: string): string | null {
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const d = (parsed as { detail: unknown }).detail;
      return typeof d === "string" && d ? d : null;
    }
  } catch {
    /* not JSON */
  }
  return null;
}

function mkMessage(
  role: "user" | "assistant",
  text: string,
  extra: Partial<AskMessage> = {},
): AskMessage {
  return { id: newLocalId(), role, text, ...extra };
}

async function safeBody(response: Response): Promise<string> {
  try {
    const t = await response.text();
    return t.slice(0, 500);
  } catch {
    return "";
  }
}
