import { useEffect, useMemo, useRef, useState } from "react";
import {
  Send,
  MessageSquare,
  Loader2,
  Check,
  ShieldCheck,
  TriangleAlert,
  ChevronRight,
  ChevronDown, Clock, Bookmark, X } from "lucide-react";
import { cn } from "../app/lib/cn";
import { useMapData } from "../app/data/MapDataProvider";
import { memoryTitleFromQuestion, stripCitationMarkers } from "../app/lib/regions";
import { toastInfo } from "../app/lib/toast";
import { useAskThreadStore } from "./askThreadStore";
import { SaveMemoryDialog, type SaveMemoryDraft } from "./SaveMemoryDialog";
import { useSelectionInside } from "./useSelectionInside";
import { ModelQuickSwitch } from "./ModelQuickSwitch";
import { useMapTimelineStore } from "../app/lib/mapTimelineStore";
import { extractCitationIds } from "./useAskStream";
import type { AskSession } from "./useAskSession";
import { AssistantMarkdown } from "./AssistantMarkdown";
import { CitationChip } from "./CitationChip";
import { parseTerrainOverview, type TerrainFocusTarget } from "./citationDisplay";
import type { SourceInspectorTarget } from "./SourceInspector";
import type { AgentStep, AskMessage, Citation } from "./types";

type Props = {
  /** The conversation's session state — settings, draft, streamed messages —
   *  owned by the caller (`AskDock`, via `useAskSession`). Messages and the
   *  draft live in the persisted thread store, so they survive unmounts. */
  session: AskSession;
  /** "Show on terrain" — focus a tag or region on the 3D map without
   *  navigating away from the chat. */
  onFocusTerrain?: (target: TerrainFocusTarget) => void;
  /** "View source" — open the citation source inspector for a document
   *  passage backing a claim. */
  onViewSource?: (target: SourceInspectorTarget) => void;
};

/**
 * Ask Mnemify — chat surface grounded in the compiled map.
 *
 * Lives inside a SideDrawer on the home page. Renders the session passed in
 * via `session` (see `useAskSession`) and streams answers from `/api/ask`
 * (BYOK) over SSE; citation popovers trigger the parent's
 * `onFocusTerrain`/`onViewSource` for "Show on terrain" / "View source"
 * without leaving the conversation.
 */
export function AskPanel({ session, onFocusTerrain, onViewSource }: Props) {
  const { settings, setSettings, draft, setDraft, messages, isStreaming, send, cancel, reset } =
    session;
  const listRef = useRef<HTMLDivElement | null>(null);
  // Only auto-scroll while the user is already at (or near) the bottom —
  // otherwise every streamed delta yanks them back down while they're
  // reading up-thread. Starts true so the initial send still lands at the
  // bottom; a manual scroll up during streaming flips it off until the user
  // scrolls back down (or sends the next message).
  const stickToBottomRef = useRef(true);
  const NEAR_BOTTOM_PX = 80;

  const onScroll = () => {
    const el = listRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottomRef.current = distanceFromBottom < NEAR_BOTTOM_PX;
  };

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages]);

  const asOf = useMapTimelineStore((s) => s.asOf);

  // Region scope: the active thread may belong to one region workspace.
  const activeThread = useAskThreadStore((s) =>
    s.threads.find((t) => t.id === s.activeThreadId) ?? null,
  );
  const regionId = activeThread?.regionId ?? null;
  const mapData = useMapData().data;
  const scopedRegion = regionId ? mapData?.indexes.regionsById.get(regionId) ?? null : null;
  const scopeName = scopedRegion?.name ?? (regionId ? "Unassigned region" : null);
  const clearScope = () => {
    if (!activeThread) return;
    const store = useAskThreadStore.getState();
    if (activeThread.messages.length === 0) {
      store.setThreadRegion(activeThread.id, null);
    } else {
      // A scoped conversation stays scoped; asking the whole map is a new thread.
      store.newThread();
      toastInfo("Started a new conversation across the whole map.");
    }
  };

  // Save to memory — whole answer, or a highlighted span of one.
  const [memoryDraft, setMemoryDraft] = useState<SaveMemoryDraft | null>(null);
  const selection = useSelectionInside(listRef);
  const draftFor = (m: AskMessage, text: string, kind: SaveMemoryDraft["kind"]): SaveMemoryDraft | null => {
    if (!regionId) return null;
    const idx = messages.findIndex((x) => x.id === m.id);
    const question = [...messages.slice(0, Math.max(0, idx))].reverse().find((x) => x.role === "user");
    const used = new Set(m.usedCitationIds || []);
    const citations = (m.citations || []).filter((c) => used.size === 0 || used.has(c.citation_id));
    return {
      regionId,
      regionName: scopeName ?? "this region",
      title: memoryTitleFromQuestion(question?.text),
      body: kind === "selection" ? text : stripCitationMarkers(text),
      kind,
      citations,
      sourceNoteIds: [...new Set(citations.flatMap((c) => c.source_note_ids || []))],
      origin: { thread_id: activeThread?.id, message_id: m.id, label: activeThread?.title },
    };
  };
  const saveSelection = () => {
    if (!selection) return;
    const m = messages.find((x) => x.id === selection.messageId && x.role === "assistant");
    if (!m) return;
    const d = draftFor(m, selection.text, "selection");
    if (d) setMemoryDraft(d);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isStreaming) return;
    const q = draft.trim();
    if (!q) return;
    setDraft("");
    // Sending a message always returns to the live edge, even if the user
    // had scrolled up to reread something.
    stickToBottomRef.current = true;
    await send(q);
  };

  // Auto-grow the composer with its content (1 → ~8 rows; the max-h class
  // caps it and switches to internal scrolling beyond that).
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    const el = composerRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [draft]);

  const onComposerKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void onSubmit(e);
    } else if (e.key === "Escape") {
      e.currentTarget.blur();
    }
  };

  const placeholder = useMemo(() => {
    if (scopeName) return `Ask about ${scopeName}…`;
    return "Ask anything about your compiled map — e.g. how does Project Phoenix relate to OCR accuracy?";
  }, [scopeName]);

  return (
    // Transparent so the dock's cartographer backdrop shows through; the
    // dock's aside supplies the cream surface.
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-transparent pt-1">
      <header className="shrink-0 px-4 pb-3">
        <div className="flex items-center gap-2 font-serif text-lg text-ink">
          <MessageSquare size={16} strokeWidth={1.5} aria-hidden />
          Ask Mnemify
        </div>
        <p className="mt-1 font-sans text-xs leading-relaxed text-muted">
          {settings.provider === "claude"
            ? "Grounded in your compiled knowledge graph. Explores it with Claude — via your local Claude Code login or your API key."
            : "Grounded in your compiled knowledge graph. Bring your own OpenAI key."}
        </p>
        {scopeName ? (
          <div
            className={cn(
              "mt-2 inline-flex max-w-full items-center gap-2 rounded-full border px-2.5 py-1 font-sans text-xs",
              scopedRegion ? "border-magenta/30 bg-magenta/10 text-ink" : "border-hair bg-bone/60 text-muted",
            )}
            data-testid="ask-scope-chip"
          >
            {scopedRegion ? (
              <span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: scopedRegion.color }} aria-hidden />
            ) : null}
            <span className="truncate">
              <span className="text-muted">Region:</span> {scopeName}
            </span>
            <button
              type="button"
              onClick={clearScope}
              aria-label="Ask the whole map instead"
              title="Ask the whole map instead"
              className="grid h-4 w-4 shrink-0 place-items-center rounded-full text-muted hover:bg-ink/10 hover:text-ink"
            >
              <X size={11} strokeWidth={2} />
            </button>
          </div>
        ) : null}
      </header>

      <div
        ref={listRef}
        onScroll={onScroll}
        className="relative min-h-[80px] flex-1 space-y-4 overflow-y-auto px-4 pb-4"
        aria-live="polite"
        aria-busy={isStreaming}
      >
        {selection && regionId ? (
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={saveSelection}
            className="glass-panel absolute z-10 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-sans text-[11px] text-ink shadow-md hover:text-magenta"
            style={{ top: selection.top, left: selection.left }}
          >
            <Bookmark size={11} strokeWidth={1.75} aria-hidden />
            Save selection to memory
          </button>
        ) : null}
        {messages.length === 0 ? (
          <p className="font-sans text-sm text-muted leading-relaxed">
            No messages yet. Try a question about a tag, person, or theme that
            appears on the 3D map.
          </p>
        ) : null}
        {messages.map((m) => (
          <article
            key={m.id}
            data-message-id={m.id}
            className={cn(
              "rounded-lg border px-3 py-2 font-sans text-sm leading-relaxed",
              m.role === "user"
                ? "border-ink/15 bg-ink/5 text-ink"
                : "border-hair bg-cream text-ink",
            )}
          >
            <div className="mb-1 flex items-center gap-2 text-[10px] uppercase tracking-wide text-muted">
              {m.role === "user" ? "You" : "Mnemify"}
              {m.asOf ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-magenta/10 px-1.5 py-px normal-case tracking-normal text-magenta">
                  <Clock size={10} strokeWidth={1.75} aria-hidden />
                  as of {formatAsOf(m.asOf)}
                </span>
              ) : null}
            </div>
            {m.steps && m.steps.length > 0 ? (
              <StepTimeline
                steps={m.steps}
                pending={Boolean(m.pending)}
                usedCitationCount={(m.usedCitationIds || []).length}
              />
            ) : null}
            {m.role === "assistant" ? (
              <AssistantMarkdown
                text={m.text || (m.pending && !m.steps?.length ? "…" : "")}
                citations={m.citations || []}
                onFocusTerrain={onFocusTerrain}
                onViewSource={onViewSource}
              />
            ) : (
              <div className="whitespace-pre-wrap">{m.text}</div>
            )}
            {m.role === "assistant" ? <VerifiedLine message={m} /> : null}
            {m.role === "assistant" && regionId && !m.pending && !m.error && m.text.trim() ? (
              <button
                type="button"
                onClick={() => {
                  const d = draftFor(m, m.text, "answer");
                  if (d) setMemoryDraft(d);
                }}
                className="mt-2 inline-flex items-center gap-1 rounded-full border border-hair px-2 py-0.5 font-sans text-[11px] text-muted transition-colors hover:border-magenta/40 hover:text-magenta"
              >
                <Bookmark size={11} strokeWidth={1.75} aria-hidden />
                Save to memory
              </button>
            ) : null}
            <GroundedInSources
              message={m}
              onFocusTerrain={onFocusTerrain}
              onViewSource={onViewSource}
            />
            {m.error ? (
              <div className="mt-2 text-[12px] text-red-600">{m.error}</div>
            ) : null}
          </article>
        ))}
      </div>

      <form onSubmit={onSubmit} className="shrink-0 border-t border-hair px-4 py-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={composerRef}
            rows={1}
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onComposerKeyDown}
            placeholder={placeholder}
            aria-label="Ask a question"
            className="max-h-44 flex-1 resize-none overflow-y-auto rounded-md border border-hair bg-cream px-3 py-2 font-sans text-sm leading-relaxed outline-none focus:border-ink"
          />
          {isStreaming ? (
            <button
              type="button"
              onClick={cancel}
              className="rounded-md border border-hair px-3 py-2 font-sans text-xs text-muted hover:text-ink"
            >
              Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={!draft.trim()}
              className="rounded-md bg-ink px-3 py-2 text-cream disabled:opacity-50"
              aria-label="Send"
            >
              <Send size={14} strokeWidth={1.5} />
            </button>
          )}
        </div>
        <div className="mt-2 flex items-center justify-between">
          <ModelQuickSwitch settings={settings} onChange={setSettings} />
          {asOf !== null ? (
            <span className="inline-flex items-center gap-1 font-sans text-[10px] text-magenta">
              <Clock size={10} strokeWidth={1.75} aria-hidden />
              Asking as of {formatAsOf(new Date(asOf).toISOString().slice(0, 10))} — close the timeline to ask about today
            </span>
          ) : (
            <span className="font-sans text-[10px] text-muted" aria-hidden>
              Enter to send · Shift+Enter for a new line
            </span>
          )}
        </div>
      </form>

      {messages.length > 0 ? (
        <button
          type="button"
          onClick={reset}
          className="shrink-0 border-t border-hair py-2 font-sans text-xs text-muted hover:text-ink"
        >
          Clear conversation
        </button>
      ) : null}
      <SaveMemoryDialog draft={memoryDraft} onClose={() => setMemoryDraft(null)} />
    </div>
  );
}

/**
 * Live agent-exploration timeline. Expanded while the answer is pending so
 * the user sees the terrain being walked; collapses to a one-line summary
 * (still expandable) once the answer lands.
 */
function StepTimeline({
  steps,
  pending,
  usedCitationCount,
}: {
  steps: AgentStep[];
  pending: boolean;
  usedCitationCount: number;
}) {
  const [expanded, setExpanded] = useState<boolean | null>(null);
  const open = expanded ?? pending;

  const overview = parseTerrainOverview(steps);
  const collapsedLabel = pending
    ? "Exploring your map…"
    : overview
      ? `Explored ${overview.nodes.toLocaleString()} nodes · ${overview.edges.toLocaleString()} relationships` +
        (usedCitationCount > 0
          ? ` · ${usedCitationCount} relevant source${usedCitationCount === 1 ? "" : "s"}`
          : "")
      : `Explored your map in ${steps.length} step${steps.length === 1 ? "" : "s"}`;

  return (
    <div className="mb-2 rounded-md border border-hair bg-bone/40 px-2 py-1.5">
      <button
        type="button"
        onClick={() => setExpanded(!open)}
        className="flex w-full items-center gap-1 font-sans text-[11px] uppercase tracking-wide text-muted hover:text-ink"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown size={12} strokeWidth={1.5} aria-hidden />
        ) : (
          <ChevronRight size={12} strokeWidth={1.5} aria-hidden />
        )}
        {collapsedLabel}
      </button>
      {open ? (
        <ol className="mt-1 space-y-0.5">
          {steps.map((s) => (
            <li
              key={s.id}
              className="flex items-start gap-1.5 font-sans text-[12px] leading-relaxed text-ink"
            >
              <span className="mt-[3px] shrink-0" aria-hidden>
                {s.status === "running" ? (
                  <Loader2 size={11} strokeWidth={1.5} className="animate-spin" />
                ) : s.status === "error" ? (
                  <TriangleAlert size={11} strokeWidth={1.5} className="text-amber-600" />
                ) : (
                  <Check size={11} strokeWidth={1.5} className="text-muted" />
                )}
              </span>
              <span>
                {s.label}
                {s.detail ? (
                  <span className="text-muted"> — {s.detail}</span>
                ) : null}
              </span>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}

/**
 * The trust line — makes the server-side citation verification visible.
 * The server parses which [cN] markers the answer actually used and DROPS
 * ids that don't exist in the retrieval registry, so "verified" here is a
 * real claim, not decoration. Dropped count = markers still present in the
 * final text that the server refused to endorse.
 */
function VerifiedLine({ message }: { message: AskMessage }) {
  if (message.pending || message.error) return null;
  const used = message.usedCitationIds || [];
  if (used.length === 0 || message.citationsFallback) return null;
  const claimed = extractCitationIds(message.text);
  const dropped = claimed.filter((id) => !used.includes(id)).length;
  return (
    <p className="mt-2 flex items-center gap-1.5 font-sans text-[11px] text-muted">
      <ShieldCheck size={12} strokeWidth={1.5} aria-hidden className="text-success" />
      {used.length} citation{used.length === 1 ? "" : "s"} verified against your
      sources
      {dropped > 0
        ? ` · ${dropped} unverified reference${dropped === 1 ? "" : "s"} removed`
        : ""}
    </p>
  );
}

/**
 * Collapsed-by-default backup traceability for a message's citations — the
 * inline citation groups in `AssistantMarkdown` are the primary way to
 * inspect sources now, so this full list is de-emphasized rather than
 * always-visible. Only the citations the answer actually used are listed
 * (in citation order); nothing renders before the first `[cN]` marker lands.
 */
function GroundedInSources({
  message,
  onFocusTerrain,
  onViewSource,
}: {
  message: AskMessage;
  onFocusTerrain?: (target: TerrainFocusTarget) => void;
  onViewSource?: (target: SourceInspectorTarget) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const used = message.usedCitationIds || [];
  const byId = new Map((message.citations || []).map((c) => [c.citation_id, c]));
  const cited = used
    .map((id) => byId.get(id))
    .filter((c): c is Citation => Boolean(c));

  if (cited.length === 0) return null;

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1 font-sans text-[11px] uppercase tracking-wide text-muted hover:text-ink"
        aria-expanded={expanded}
      >
        {expanded ? (
          <ChevronDown size={12} strokeWidth={1.5} aria-hidden />
        ) : (
          <ChevronRight size={12} strokeWidth={1.5} aria-hidden />
        )}
        Grounded in {cited.length} source{cited.length === 1 ? "" : "s"}
        {message.citationsFallback ? " (related context)" : ""}
      </button>
      {expanded ? (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {cited.map((c) => (
            <CitationChip
              key={c.citation_id}
              citation={c}
              onFocusTerrain={onFocusTerrain}
              onViewSource={onViewSource}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** `YYYY-MM-DD` → "14 Mar 2025", read as a UTC day so it never shifts. */
function formatAsOf(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(undefined, {
    year: "numeric", month: "short", day: "numeric", timeZone: "UTC",
  });
}
