import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { HarvestRun } from "../api/harvest";
import { SourceBadge } from "./SourceBadge";
import { Badge } from "./ui/Badge";
import { relativeTime } from "../lib/relativeTime";
import { formatDuration } from "../lib/formatEta";
import { cn } from "../lib/cn";

interface HarvestHistoryListProps {
  runs: HarvestRun[];
}

export function HarvestHistoryList({ runs }: HarvestHistoryListProps) {
  if (runs.length === 0) {
    return (
      <div className="bg-bone/40 border border-hair rounded-2xl p-12 text-center">
        <p className="font-serif text-xl text-ink mb-2">No harvest history yet.</p>
        <p className="font-sans text-sm text-muted max-w-prose mx-auto">
          Once you trigger a harvest from the Connections page, runs will appear here.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-bone/40 border border-hair rounded-2xl overflow-hidden">
      <div className="grid grid-cols-[180px_1fr_120px_100px_100px_40px] items-center gap-4 px-5 py-2 border-b border-hair bg-bone/60 font-sans text-[10px] uppercase tracking-eyebrow text-muted/90">
        <span>Started</span>
        <span>Sources</span>
        <span className="text-right">Harvested</span>
        <span className="text-right">Failed</span>
        <span>Duration</span>
        <span></span>
      </div>
      <ul>
        {runs.map((run) => (
          <RunRow key={run.id ?? `${run.started_at}`} run={run} />
        ))}
      </ul>
    </div>
  );
}

function RunRow({ run }: { run: HarvestRun }) {
  const [open, setOpen] = useState(false);
  const duration =
    run.finished_at && run.started_at
      ? (new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000
      : null;

  return (
    <li className="border-b border-hair/40 last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left grid grid-cols-[180px_1fr_120px_100px_100px_40px] items-center gap-4 px-5 py-3 hover:bg-cream/60 transition-colors"
      >
        <span className="font-sans text-xs text-ink tabular-nums">
          {relativeTime(run.started_at)}
        </span>
        <span className="flex items-center gap-2 flex-wrap min-w-0">
          {run.sources.length === 0 ? (
            <span className="font-sans text-xs text-muted">—</span>
          ) : (
            run.sources.map((s) => (
              <SourceBadge key={s} source={s} size="sm" />
            ))
          )}
        </span>
        <span className="font-mono text-xs text-ink tabular-nums text-right">
          +{run.docs_harvested.toLocaleString()}
        </span>
        <span
          className={cn(
            "font-mono text-xs tabular-nums text-right",
            run.docs_failed > 0 ? "text-rose" : "text-muted",
          )}
        >
          {run.docs_failed.toLocaleString()}
        </span>
        <span className="font-mono text-xs text-muted tabular-nums">
          {formatDuration(duration)}
        </span>
        <span className="text-muted">
          {open ? (
            <ChevronDown size={14} strokeWidth={1.5} />
          ) : (
            <ChevronRight size={14} strokeWidth={1.5} />
          )}
        </span>
      </button>
      {open && (
        <div className="px-5 py-3 border-t border-hair/40 bg-cream/40">
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 font-sans text-xs text-muted">
            <Stat label="Run ID" value={<code className="font-mono text-[10px]">{run.id ?? "(none)"}</code>} />
            <Stat label="Status" value={<Badge tone={statusTone(run.status)}>{run.status}</Badge>} />
            <Stat label="Started" value={new Date(run.started_at).toLocaleString()} />
            <Stat
              label="Finished"
              value={run.finished_at ? new Date(run.finished_at).toLocaleString() : "—"}
            />
          </div>
        </div>
      )}
    </li>
  );
}

function statusTone(status: string): "sage" | "rose" | "muted" {
  if (status === "complete") return "sage";
  if (status === "failed" || status === "in_progress" || status === "running") return "rose";
  return "muted";
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="font-sans text-[10px] uppercase tracking-eyebrow text-muted/80 w-16">{label}</span>
      <span className="text-ink">{value}</span>
    </div>
  );
}
