import { beforeEach, describe, expect, it } from "vitest";
import { useAskThreadStore } from "./askThreadStore";
import type { AskMessage } from "./types";

function msg(over: Partial<AskMessage>): AskMessage {
  return { id: Math.random().toString(36).slice(2), role: "user", text: "hi", ...over };
}

beforeEach(() => {
  useAskThreadStore.setState({
    threads: [],
    activeThreadId: null,
    draft: "",
    streamingThreadId: null,
  });
});

describe("askThreadStore", () => {
  it("ensureActiveThread creates once and is then stable", () => {
    const s = useAskThreadStore.getState();
    const id = s.ensureActiveThread();
    expect(useAskThreadStore.getState().ensureActiveThread()).toBe(id);
    expect(useAskThreadStore.getState().threads).toHaveLength(1);
  });

  it("titles the thread from the first user message, truncated", () => {
    const s = useAskThreadStore.getState();
    const id = s.ensureActiveThread();
    const long = "x".repeat(100);
    useAskThreadStore.getState().appendMessages(id, [msg({ text: long })]);
    const thread = useAskThreadStore.getState().threads[0];
    expect(thread.title.length).toBeLessThanOrEqual(64);
    expect(thread.title.endsWith("…")).toBe(true);
  });

  it("patchMessage updates only the target message in the target thread", () => {
    const s = useAskThreadStore.getState();
    const id = s.ensureActiveThread();
    const a = msg({ id: "a", role: "assistant", text: "", pending: true });
    useAskThreadStore.getState().appendMessages(id, [msg({ id: "u" }), a]);
    useAskThreadStore.getState().patchMessage(id, "a", (m) => ({ ...m, text: "done", pending: false }));
    const messages = useAskThreadStore.getState().threads[0].messages;
    expect(messages.find((m) => m.id === "a")).toMatchObject({ text: "done", pending: false });
    expect(messages.find((m) => m.id === "u")?.text).toBe("hi");
  });

  it("streaming writes keep landing in their thread after a switch", () => {
    const s = useAskThreadStore.getState();
    const first = s.ensureActiveThread();
    useAskThreadStore.getState().appendMessages(first, [msg({ id: "u1" }), msg({ id: "a1", role: "assistant", text: "" })]);
    useAskThreadStore.getState().newThread();
    const second = useAskThreadStore.getState().activeThreadId;
    expect(second).not.toBe(first);
    // The in-flight stream still patches `first` by captured id.
    useAskThreadStore.getState().patchMessage(first, "a1", (m) => ({ ...m, text: "streamed" }));
    const firstThread = useAskThreadStore.getState().threads.find((t) => t.id === first)!;
    expect(firstThread.messages.find((m) => m.id === "a1")?.text).toBe("streamed");
  });

  it("newThread reuses an empty active thread instead of stacking blanks", () => {
    const s = useAskThreadStore.getState();
    s.ensureActiveThread();
    useAskThreadStore.getState().newThread();
    useAskThreadStore.getState().newThread();
    expect(useAskThreadStore.getState().threads).toHaveLength(1);
  });

  it("deleteThread falls back to the next thread", () => {
    const s = useAskThreadStore.getState();
    const first = s.ensureActiveThread();
    useAskThreadStore.getState().appendMessages(first, [msg({})]);
    useAskThreadStore.getState().newThread();
    const second = useAskThreadStore.getState().activeThreadId!;
    useAskThreadStore.getState().deleteThread(second);
    expect(useAskThreadStore.getState().activeThreadId).toBe(first);
  });

  it("caps threads at 30, evicting the least recently updated", () => {
    for (let i = 0; i < 35; i++) {
      useAskThreadStore.setState({ activeThreadId: null });
      const id = useAskThreadStore.getState().ensureActiveThread();
      useAskThreadStore.getState().appendMessages(id, [msg({ text: `q${i}` })]);
    }
    expect(useAskThreadStore.getState().threads.length).toBeLessThanOrEqual(30);
  });

  it("tracks the streaming thread outside component state", () => {
    // The dock unmounts when closed, so an in-flight stream's status has to
    // live in the store or the UI comes back showing Send instead of Stop.
    const id = useAskThreadStore.getState().ensureActiveThread();
    useAskThreadStore.getState().setStreamingThread(id);
    expect(useAskThreadStore.getState().streamingThreadId).toBe(id);
    useAskThreadStore.getState().setStreamingThread(null);
    expect(useAskThreadStore.getState().streamingThreadId).toBeNull();
  });

  it("never persists streaming status (a reload kills the request)", () => {
    const persisted = JSON.parse(
      JSON.stringify(
        (useAskThreadStore.persist.getOptions().partialize ?? ((s) => s))(
          useAskThreadStore.getState(),
        ),
      ),
    );
    expect(persisted).not.toHaveProperty("streamingThreadId");
    expect(persisted).toHaveProperty("threads");
  });

  it("clearActiveThread empties messages but keeps the thread", () => {
    const s = useAskThreadStore.getState();
    const id = s.ensureActiveThread();
    useAskThreadStore.getState().appendMessages(id, [msg({})]);
    useAskThreadStore.getState().clearActiveThread();
    const state = useAskThreadStore.getState();
    expect(state.threads[0].messages).toHaveLength(0);
    expect(state.activeThreadId).toBe(id);
  });
});
