import { useNavigate } from "react-router-dom";
import { ArrowRight, Sparkles } from "lucide-react";
import { Card, CardContent } from "./ui/Card";
import { Button } from "./ui/Button";
import { SourceBadge } from "./SourceBadge";
import { formatBytes } from "./DocTable";
import { formatDuration } from "../lib/formatEta";
import type { HarvestCurrent, HarvestSummary } from "../api/harvest";
import { totalChanges, useChanges } from "../api/changes";
import { ChangePill, changeAttribution } from "./RecentChangesPanel";

interface CompletionSummaryProps {
  summary: HarvestSummary;
  perSource: HarvestCurrent["sources"];
  cancelled?: boolean;
}

const NUDGE_MAX_ROWS = 6;

export function CompletionSummary({ summary, perSource, cancelled }: CompletionSummaryProps) {
  const navigate = useNavigate();
  const { data: changes } = useChanges("last_compile", { enabled: !cancelled });
  const pendingTotal = changes ? totalChanges(changes.summary) : 0;

  const headline = cancelled
    ? "Harvest cancelled."
    : summary.harvested === 0
      ? "All memories already current."
      : `Your map learned ${summary.harvested.toLocaleString()} new memor${summary.harvested === 1 ? "y" : "ies"}.`;

  const subheadline = cancelled
    ? `${summary.harvested.toLocaleString()} document${summary.harvested === 1 ? " was" : "s were"} saved before you stopped it.`
    : summary.harvested === 0
      ? `Nothing new since the last run. ${summary.skipped.toLocaleString()} unchanged.`
      : `${summary.failed.toLocaleString()} failed · ${summary.skipped.toLocaleString()} unchanged · ${formatDuration(summary.seconds)} elapsed.`;

  const sourceEntries = Object.entries(perSource);

  return (
    <div className="space-y-8">
      <Card className="bg-lavender/15">
        <CardContent className="p-8">
          <h2 className="font-serif text-3xl text-ink leading-tight">{headline}</h2>
          <p className="font-sans text-sm text-muted mt-2 max-w-prose">{subheadline}</p>
        </CardContent>
      </Card>

      {sourceEntries.length > 0 && (
        <section>
          <p className="eyebrow mb-3">By source</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {sourceEntries.map(([source, prog]) => (
              <div
                key={source}
                className="flex items-center justify-between gap-4 px-4 py-3 rounded-xl bg-bone/40 border border-hair"
              >
                <SourceBadge source={source} />
                <div className="flex items-baseline gap-3 font-mono text-xs text-muted tabular-nums">
                  <span className="text-ink">
                    +{prog.done.toLocaleString()} new
                  </span>
                  <span>· {prog.already_harvested.toLocaleString()} unchanged</span>
                  {(prog.bytes ?? 0) > 0 && (
                    <span>· {formatBytes(prog.bytes ?? 0)}</span>
                  )}
                  {prog.failed > 0 && (
                    <span className="text-rose">· {prog.failed.toLocaleString()} failed</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {!cancelled && changes?.compile_running && (
        <p className="font-sans text-sm text-muted -mt-2 max-w-prose">
          Compiling your map now — these documents are being folded in.
        </p>
      )}

      {!cancelled && !changes?.compile_running && pendingTotal > 0 && (
        <section>
          <p className="eyebrow mb-3">
            {pendingTotal.toLocaleString()} page{pendingTotal === 1 ? "" : "s"} changed since
            your last compile
          </p>
          <div className="rounded-xl bg-bone/40 border border-hair divide-y divide-hair/60">
            {changes!.changes.slice(0, NUDGE_MAX_ROWS).map((c) => {
              const who = changeAttribution(c);
              return (
                <div
                  key={`${c.source}-${c.source_id}`}
                  className="flex items-center justify-between gap-4 px-4 py-2.5"
                >
                  <div className="min-w-0 flex items-center gap-2">
                    <ChangePill change={c.change} />
                    <span
                      className={`font-sans text-sm truncate ${c.change === "deleted" ? "line-through text-muted" : "text-ink"}`}
                    >
                      {c.title}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 shrink-0 font-sans text-xs text-muted">
                    {who && <span>{who}</span>}
                    <SourceBadge source={c.source} showLabel={false} />
                  </div>
                </div>
              );
            })}
          </div>
          {pendingTotal > NUDGE_MAX_ROWS && (
            <p className="font-sans text-xs text-muted mt-2">
              …and {(pendingTotal - NUDGE_MAX_ROWS).toLocaleString()} more.
            </p>
          )}
        </section>
      )}

      {!cancelled && !changes?.compile_running && pendingTotal === 0 && changes && (
        <p className="font-sans text-sm text-muted -mt-2 max-w-prose">
          Your map is already up to date — nothing new to compile.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={() => navigate("/build/compile")}>
          <Sparkles size={14} strokeWidth={1.5} />
          Compile now
          <ArrowRight size={14} strokeWidth={1.5} />
        </Button>
      </div>
    </div>
  );
}
