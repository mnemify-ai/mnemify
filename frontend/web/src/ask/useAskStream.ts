import { useCallback } from "react";
import { apiUrl } from "../app/api/client";
import { newLocalId, useActiveThreadMessages, useAskThreadStore } from "./askThreadStore";
import type { AgentStep, AskMessage, AskSettings, Citation } from "./types";
import { activeKey, wireProvider } from "./types";
import { useMapPulseStore } from "../app/lib/mapPulseStore";

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
      const patch = (
        messageId: string,
        fn: (m: AskMessage) => AskMessage,
      ) => useAskThreadStore.getState().patchMessage(threadId, messageId, fn);

      // No client-side "is a key set?" guard: the browser key is only an
      // override. `/api/ask` falls back to the key saved in Settings → AI &
      // Models, and answers 401 when neither exists — `describeAskFailure`
      // turns that into the "add your key" message below.
      const key = activeKey(settings);

      const userMsg = mkMessage("user", query.trim());
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

      store.setStreamingThread(threadId);
      const controller = new AbortController();
      activeAbort = controller;
      try {
        const response = await fetch(apiUrl("/api/ask"), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(key ? { Authorization: `Bearer ${key}` } : {}),
          },
          body: JSON.stringify({
            query,
            provider: wireProvider(settings),
            model: settings.model,
            history,
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
          onCitations: (citations) => {
            patch(assistantId, (m) => ({ ...m, citations }));
          },
          onDelta: (text) => {
            patch(assistantId, (m) => {
              const nextText = m.text + text;
              // Surface chips live as [cN] markers stream in; the server's
              // citations_used event reconciles at the end.
              return {
                ...m,
                text: nextText,
                pending: true,
                usedCitationIds: extractCitationIds(nextText),
              };
            });
          },
          onAgentStep: (step) => {
            // Mirror the agent's exploration onto the 3D map. Fire-and-forget:
            // the store self-expires, so a dock closed mid-answer leaves
            // nothing behind.
            useMapPulseStore.getState().pulseRegions(step.node_ids);
            patch(assistantId, (m) => {
              const steps = m.steps ? [...m.steps] : [];
              const idx = steps.findIndex((s) => s.id === step.id);
              if (idx === -1) steps.push(step);
              else steps[idx] = step;
              return { ...m, steps };
            });
          },
          onCitationsUsed: (used, fallback) => {
            patch(assistantId, (m) => ({
              ...m,
              usedCitationIds: used,
              citationsFallback: fallback,
            }));
          },
          onError: (msg) => {
            patch(assistantId, (m) => ({ ...m, error: msg, pending: false }));
          },
          onDone: () => {
            patch(assistantId, (m) => ({ ...m, pending: false }));
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
  onCitations: (citations: Citation[]) => void;
  onDelta: (text: string) => void;
  onAgentStep: (step: AgentStep) => void;
  onCitationsUsed: (used: string[], fallback: boolean) => void;
  onError: (msg: string) => void;
  onDone: () => void;
};

const CITATION_MARKER = /\[(c\d+)\]/g;

/** Citation ids referenced in the text, deduped in first-appearance order. */
export function extractCitationIds(text: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const match of text.matchAll(CITATION_MARKER)) {
    if (!seen.has(match[1])) {
      seen.add(match[1]);
      out.push(match[1]);
    }
  }
  return out;
}

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
      if (currentEvent === "citations") {
        handlers.onCitations((payload?.citations as Citation[]) || []);
      } else if (currentEvent === "delta") {
        handlers.onDelta(payload?.text || "");
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
