import { useState } from "react";
import { ArrowRight, FileText } from "lucide-react";
import { SectionCard } from "./SectionCard";
import { Skeleton } from "../ui/Skeleton";
import type { RegionSignal, RegionSignalKind } from "../../api/regions";
import { cleanTitle } from "../../lib/actionItems";
import { KIND_META } from "../../../knowledgeMap/chrome/SignalGroups";

/** "Decisions" / "Open questions" — the first few items, the rest behind "+N more". */
const PREVIEW_ROWS = 3;

export function SignalCard({
  kind,
  title,
  items,
  total,
  loading,
  onOpenEvidence,
}: {
  kind: RegionSignalKind;
  title: string;
  items: RegionSignal[];
  total: number;
  loading: boolean;
  onOpenEvidence: (signal: RegionSignal) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const meta = KIND_META[kind];
  const { Icon } = meta;
  const shown = expanded ? items : items.slice(0, PREVIEW_ROWS);
  return (
    <SectionCard eyebrow={title} className="h-full">
      {loading && items.length === 0 ? (
        <div className="space-y-2"><Skeleton width="70%" /><Skeleton width="95%" /><Skeleton width="40%" /></div>
      ) : items.length === 0 ? (
        <p className="font-sans text-sm text-muted">
          {kind === "decision" ? "No decisions recorded in this region yet." : "No open questions found in this region."}
        </p>
      ) : (
        <ul className="space-y-4">
          {shown.map((s) => (
            <li key={s.id} className="flex items-start gap-3">
              <span className="mt-0.5 inline-grid h-9 w-9 shrink-0 place-items-center rounded-full" style={{ background: `${meta.color}1A` }}>
                <Icon size={16} strokeWidth={2} color={meta.color} aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <p className="font-sans text-sm font-semibold leading-snug text-ink">{cleanTitle(s.title)}</p>
                {s.summary ? <p className="mt-1 font-sans text-sm leading-relaxed text-muted">{s.summary}</p> : null}
                {s.source_note_title ? (
                  <button
                    type="button"
                    onClick={() => onOpenEvidence(s)}
                    className="mt-2 inline-flex items-center gap-1.5 font-sans text-xs text-muted hover:text-magenta"
                  >
                    Source:
                    <FileText size={12} strokeWidth={1.5} aria-hidden />
                    <span className="text-magenta">{s.source_note_title}</span>
                    <ArrowRight size={12} strokeWidth={1.5} className="text-magenta" aria-hidden />
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
      {items.length > PREVIEW_ROWS ? (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-3 font-sans text-xs text-magenta hover:underline underline-offset-4"
        >
          {expanded ? "Show less" : `+${total - PREVIEW_ROWS} more`}
        </button>
      ) : null}
    </SectionCard>
  );
}
