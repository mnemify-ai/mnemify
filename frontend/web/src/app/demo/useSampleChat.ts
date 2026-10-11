import { useCallback, useEffect, useRef, useState } from "react";
import { applyAskEvent, applyAskEventToMap } from "../../ask/askEvents";
import type { AskMessage, Citation } from "../../ask/types";
import { useMapHighlightStore } from "../lib/mapHighlightStore";
import { scheduleReplay } from "./replay";
import type { SampleChatRecord } from "./sampleStore";

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

/**
 * The sample workspace's chat: replays recorded answers through the same
 * event reducer and map effects as the live Ask stream. Local state only;
 * nothing is persisted or sent anywhere.
 */
export function useSampleChat() {
  const [messages, setMessages] = useState<AskMessage[]>([]);
  const [askedIds, setAskedIds] = useState<Set<string>>(() => new Set());
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const timers = useRef<number[]>([]);

  const stop = useCallback(() => {
    for (const t of timers.current) window.clearTimeout(t);
    timers.current = [];
  }, []);
  useEffect(() => stop, [stop]);

  const ask = useCallback(
    (record: SampleChatRecord) => {
      stop();
      // Finish whatever was streaming so it doesn't stay half-written.
      setMessages((prev) => prev.map((m) => (m.pending ? { ...m, pending: false } : m)));
      // A new question retires the previous answer's map highlight.
      useMapHighlightStore.getState().clear();
      const userId = `sample-u-${record.id}-${Date.now()}`;
      const assistantId = `sample-a-${record.id}-${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        { id: userId, role: "user", text: record.question },
        { id: assistantId, role: "assistant", text: "", pending: true, citations: [] },
      ]);
      setAskedIds((prev) => new Set(prev).add(record.id));
      setStreamingId(assistantId);

      let lastCitations: Citation[] = [];
      const plan = scheduleReplay(record.events, { reducedMotion: prefersReducedMotion() });
      const apply = (i: number) => {
        const { ev } = plan[i];
        if (ev.kind === "citations") lastCitations = ev.citations;
        applyAskEventToMap(ev, record.question, lastCitations);
        setMessages((prev) => prev.map((m) => (m.id === assistantId ? applyAskEvent(m, ev) : m)));
        if (ev.kind === "done") setStreamingId(null);
      };
      plan.forEach((p, i) => {
        timers.current.push(window.setTimeout(() => apply(i), p.atMs));
      });
      // A recording without a trailing done still settles.
      const end = (plan[plan.length - 1]?.atMs ?? 0) + 50;
      timers.current.push(
        window.setTimeout(() => {
          setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, pending: false } : m)));
          setStreamingId(null);
        }, end),
      );
    },
    [stop],
  );

  const reset = useCallback(() => {
    stop();
    setMessages([]);
    setAskedIds(new Set());
    setStreamingId(null);
    useMapHighlightStore.getState().clear();
  }, [stop]);

  return { messages, askedIds, isStreaming: streamingId !== null, ask, reset };
}
