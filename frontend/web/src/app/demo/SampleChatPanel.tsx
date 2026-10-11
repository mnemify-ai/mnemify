import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, ChevronRight, RotateCcw, Sparkles } from "lucide-react";
import { AskGlyph } from "../../ask/AskDock";
import { AssistantMarkdown } from "../../ask/AssistantMarkdown";
import { GroundedInSources, PendingStatus, StepTimeline, VerifiedLine } from "../../ask/AskPanel";
import type { TerrainFocusTarget } from "../../ask/citationDisplay";
import { pendingLabel } from "../../ask/pendingStatus";
import type { SourceInspectorTarget } from "../../ask/SourceInspector";
import { cn } from "../lib/cn";
import type { SampleChatRecord, SampleManifest } from "./sampleStore";
import type { useSampleChat } from "./useSampleChat";

type Props = {
  records: SampleChatRecord[];
  manifest: SampleManifest;
  chat: ReturnType<typeof useSampleChat>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onFocusTerrain: (target: TerrainFocusTarget) => void;
  onViewSource: (target: SourceInspectorTarget) => void;
};

/**
 * The sample map's chat: pick a question, watch a recorded answer replay —
 * the agent's steps pulse the regions it walks, the answer's sources light
 * up on the map, and every citation opens its document or flies the camera.
 */
export function SampleChatPanel({ records, manifest, chat, open, onOpenChange, onFocusTerrain, onViewSource }: Props) {
  const navigate = useNavigate();
  const listRef = useRef<HTMLDivElement | null>(null);
  const { messages, askedIds, isStreaming, ask, reset } = chat;
  // After the first answer the remaining questions fold into the footer.
  const [moreOpen, setMoreOpen] = useState(false);
  const pick = (r: SampleChatRecord) => {
    setMoreOpen(false);
    ask(r);
  };

  // Follow the answer as it streams.
  const lastText = messages[messages.length - 1]?.text.length ?? 0;
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, lastText]);

  if (!open) {
    // The same launcher as the real map's "Ask your map" bubble.
    return (
      <button
        type="button"
        onClick={() => onOpenChange(true)}
        aria-label="Ask the sample map"
        className="group relative inline-flex h-12 items-center gap-2 rounded-full glass-panel pl-1.5 pr-4 shadow-lg transition-transform duration-200 hover:scale-[1.03] active:scale-95"
        style={{ boxShadow: "0 8px 24px rgb(0 0 0 / 0.30), inset 0 1px 0 rgb(255 255 255 / 0.2)" }}
      >
        <span className="relative grid h-9 w-9 shrink-0 place-items-center rounded-full">
          <span
            aria-hidden
            className="absolute inset-0 rounded-full animate-pulse motion-reduce:animate-none"
            style={{
              background: "radial-gradient(circle at 50% 50%, rgb(var(--c-magenta) / 0.34), transparent 68%)",
              filter: "blur(6px)",
            }}
          />
          <AskGlyph size={20} />
        </span>
        <span className="whitespace-nowrap pr-0.5 font-sans text-sm text-ink">Ask the sample map</span>
      </button>
    );
  }

  const remaining = records.filter((r) => !askedIds.has(r.id));

  return (
    <section
      aria-label="Ask the sample map"
      // A solid surface, not frosted glass: the map behind stays crisp and the
      // answer stays readable.
      className="flex h-full max-h-full w-full flex-col overflow-hidden rounded-xl border border-hair bg-cream shadow-sm"
    >
      <header className="flex shrink-0 items-center justify-between gap-2 border-b border-hair px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <Sparkles size={15} strokeWidth={1.75} className="shrink-0 text-magenta" aria-hidden />
          <h2 className="truncate font-sans text-sm font-medium text-ink">Ask the sample map</h2>
        </div>
        <div className="flex items-center gap-1">
          {messages.length > 0 && (
            <button
              type="button"
              onClick={reset}
              title="Start over"
              aria-label="Start over"
              className="grid h-7 w-7 place-items-center rounded-full text-muted hover:bg-lavender/60 hover:text-ink"
            >
              <RotateCcw size={13} strokeWidth={1.75} aria-hidden />
            </button>
          )}
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            title="Collapse"
            aria-label="Collapse chat"
            className="grid h-7 w-7 place-items-center rounded-full text-muted hover:bg-lavender/60 hover:text-ink"
          >
            <ChevronDown size={14} strokeWidth={1.75} aria-hidden />
          </button>
        </div>
      </header>

      <div ref={listRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {messages.length === 0 && (
          <>
            <p className="font-sans text-[12.5px] leading-relaxed text-muted">
              <span className="text-ink">This is Stencil</span>, a fictional fintech, as its CTO Maya Chen would see it:{" "}
              {manifest.counts.documents ?? manifest.counts.notes} documents from Notion, Confluence, Obsidian and local notes,
              as of {formatAsOf(manifest.exportedAt)}. Ask a question and watch the map light up where Mnemify looked.
            </p>
            <QuestionList records={records} disabled={isStreaming} onPick={pick} />
          </>
        )}
        {messages.map((m) => (
          <article
            key={m.id}
            className={cn(
              "rounded-lg border px-3 py-2 font-sans text-sm leading-relaxed",
              m.role === "user" ? "border-ink/15 bg-ink/5 text-ink" : "border-hair bg-cream text-ink",
            )}
          >
            <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">{m.role === "user" ? "You" : "Mnemify"}</div>
            {m.role === "user" ? (
              <div className="whitespace-pre-wrap">{m.text}</div>
            ) : (
              <>
                {m.steps && m.steps.length > 0 && (
                  <StepTimeline steps={m.steps} pending={Boolean(m.pending)} usedCitationCount={(m.usedCitationIds || []).length} />
                )}
                {m.pending && !m.text && !m.steps?.length && (
                  <PendingStatus label={pendingLabel(m.status, (m.citations || []).length)} />
                )}
                <AssistantMarkdown
                  text={m.text}
                  citations={m.citations || []}
                  onFocusTerrain={onFocusTerrain}
                  onViewSource={onViewSource}
                />
                <VerifiedLine message={m} />
                <GroundedInSources message={m} onFocusTerrain={onFocusTerrain} onViewSource={onViewSource} />
              </>
            )}
          </article>
        ))}
      </div>

      <footer className="shrink-0 border-t border-hair px-3 py-2.5">
        {messages.length > 0 && remaining.length > 0 && (
          <div className="mb-2">
            <button
              type="button"
              onClick={() => setMoreOpen((v) => !v)}
              aria-expanded={moreOpen}
              className="flex w-full items-center gap-1 font-sans text-[11px] uppercase tracking-wide text-muted hover:text-ink"
            >
              {moreOpen ? <ChevronDown size={12} strokeWidth={1.75} aria-hidden /> : <ChevronRight size={12} strokeWidth={1.75} aria-hidden />}
              Ask another question · {remaining.length}
            </button>
            {moreOpen && (
              <div className="mt-1.5 max-h-56 overflow-y-auto">
                <QuestionList records={remaining} disabled={isStreaming} onPick={pick} />
              </div>
            )}
          </div>
        )}
        <div className="flex items-center justify-between gap-2 rounded-md border border-hair bg-bone/40 px-2.5 py-1.5">
          <span className="font-sans text-[12px] text-muted">Your own questions?</span>
          <button
            type="button"
            onClick={() => navigate("/build/sources")}
            className="shrink-0 font-sans text-[12px] font-medium text-magenta hover:underline underline-offset-4"
          >
            Connect a source →
          </button>
        </div>
      </footer>
    </section>
  );
}

/** The suggested questions, as short questions (the full wording is what
 *  gets asked, and shows on hover). */
function QuestionList({
  records,
  disabled,
  onPick,
}: {
  records: SampleChatRecord[];
  disabled: boolean;
  onPick: (r: SampleChatRecord) => void;
}) {
  return (
    <ul className="flex flex-col gap-1.5" aria-label="Suggested questions">
      {records.map((r) => (
        <li key={r.id}>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onPick(r)}
            title={r.question}
            className={cn(
              "w-full rounded-lg border border-magenta/25 bg-magenta/[0.05] px-3 py-1.5 text-left font-sans text-[12.5px] leading-snug text-ink transition-colors",
              "hover:border-magenta/55 hover:bg-magenta/[0.1] disabled:cursor-not-allowed disabled:opacity-50",
            )}
          >
            {r.label}
          </button>
        </li>
      ))}
    </ul>
  );
}

function formatAsOf(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" });
}
