// Recent changes drawer — "what does my map not know yet?"
//
// Lists documents harvested since the last compile, grouped by day and then
// by the person who changed them. Opened from the BriefingCard's "See all"
// and the TopBar pending-changes pill; the small exports (ChangePill,
// changeAttribution) are shared with the harvest CompletionSummary nudge.

import { useMemo } from "react";
import { ExternalLink, Sparkles } from "lucide-react";
import { SideDrawer } from "./ui/SideDrawer";
import { Button } from "./ui/Button";
import { SourceBadge } from "./SourceBadge";
import { relativeTime } from "../lib/relativeTime";
import { useStartCompile } from "../api/terrain";
import {
  totalChanges,
  useChanges,
  type ChangeEntry,
  type ChangeKind,
} from "../api/changes";

const PILL_STYLES: Record<ChangeKind, string> = {
  new: "bg-sage/20 text-ink",
  updated: "bg-lavender/25 text-ink",
  deleted: "bg-rose/15 text-rose",
};

const PILL_LABELS: Record<ChangeKind, string> = {
  new: "new",
  updated: "updated",
  deleted: "deleted",
};

export function ChangePill({ change }: { change: ChangeKind }) {
  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded font-mono text-[10px] uppercase tracking-wide ${PILL_STYLES[change]}`}
    >
      {PILL_LABELS[change]}
    </span>
  );
}

/** "added by Sarah Chen" / "edited by Tom Ito" — the person who made the
 * change, preferring the last editor over the original creator. */
export function changeAttribution(entry: ChangeEntry): string | null {
  const who = entry.last_modified_by || entry.author;
  if (!who) return null;
  if (entry.change === "new") return `added by ${who}`;
  if (entry.change === "deleted") return null; // source APIs don't say who deleted
  return `edited by ${who}`;
}

function dayLabel(iso: string | null): string {
  if (!iso) return "Earlier";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Earlier";
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, { month: "long", day: "numeric" });
}

interface DayGroup {
  label: string;
  authors: { name: string; entries: ChangeEntry[] }[];
}

function groupChanges(changes: ChangeEntry[]): DayGroup[] {
  const days = new Map<string, ChangeEntry[]>();
  for (const c of changes) {
    const label = dayLabel(c.changed_at);
    const list = days.get(label);
    if (list) list.push(c);
    else days.set(label, [c]);
  }
  // Insertion order is already newest-first (API sorts descending).
  return Array.from(days.entries()).map(([label, entries]) => {
    const authors = new Map<string, ChangeEntry[]>();
    for (const e of entries) {
      const who = e.last_modified_by || e.author || "Unknown";
      const list = authors.get(who);
      if (list) list.push(e);
      else authors.set(who, [e]);
    }
    return {
      label,
      authors: Array.from(authors.entries()).map(([name, list]) => ({
        name,
        entries: list,
      })),
    };
  });
}

function ChangeRow({ entry }: { entry: ChangeEntry }) {
  const title =
    entry.change === "deleted" ? (
      <span className="line-through text-muted">{entry.title}</span>
    ) : entry.url ? (
      <a
        href={entry.url}
        target="_blank"
        rel="noreferrer"
        className="text-ink hover:underline inline-flex items-center gap-1"
      >
        {entry.title}
        <ExternalLink size={11} strokeWidth={1.5} className="text-muted shrink-0" />
      </a>
    ) : (
      <span className="text-ink">{entry.title}</span>
    );

  return (
    <div className="flex items-start justify-between gap-3 py-2 border-b border-hair/60 last:border-b-0">
      <div className="min-w-0">
        <div className="font-sans text-sm leading-snug truncate">{title}</div>
        <div className="font-sans text-[11px] text-muted mt-0.5 flex items-center gap-1.5 flex-wrap">
          <ChangePill change={entry.change} />
          <SourceBadge source={entry.source} />
          {entry.space && <span>· {entry.space}</span>}
          <span>· {relativeTime(entry.changed_at)}</span>
        </div>
      </div>
    </div>
  );
}

export function RecentChangesPanel({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data, isLoading } = useChanges("last_compile", { enabled: open });
  const startCompile = useStartCompile();

  const groups = useMemo(
    () => (data ? groupChanges(data.changes) : []),
    [data],
  );
  const total = data ? totalChanges(data.summary) : 0;

  return (
    // `avoidAskDock`: reachable from the TopBar ops pill on every desktop
    // route, so without it this list lands on top of an open conversation
    // exactly the way the citation inspector used to.
    <SideDrawer open={open} onOpenChange={onOpenChange} width="440px" avoidAskDock>
      <div className="flex flex-col h-full overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-hair">
          <p className="eyebrow">Since your last compile</p>
          <h2 className="font-serif text-2xl text-ink mt-1">
            {isLoading
              ? "Checking for changes…"
              : total === 0
                ? "Nothing new"
                : `${total.toLocaleString()} page${total === 1 ? "" : "s"} changed`}
          </h2>
          {data && total > 0 && (
            <p className="font-sans text-xs text-muted mt-1">
              {data.summary.new > 0 && `${data.summary.new} new`}
              {data.summary.new > 0 && (data.summary.updated > 0 || data.summary.deleted > 0) && " · "}
              {data.summary.updated > 0 && `${data.summary.updated} updated`}
              {data.summary.updated > 0 && data.summary.deleted > 0 && " · "}
              {data.summary.deleted > 0 && `${data.summary.deleted} deleted`}
            </p>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {!isLoading && total === 0 && (
            <p className="font-sans text-sm text-muted">
              Nothing new since your last compile. Your map already knows
              everything harvested so far.
            </p>
          )}
          {groups.map((day) => (
            <section key={day.label} className="mb-5">
              <p className="eyebrow mb-2">{day.label}</p>
              {day.authors.map((a) => (
                <div key={a.name} className="mb-3">
                  <p className="font-sans text-xs text-ink/80 mb-1">
                    {a.name}
                    <span className="text-muted">
                      {" "}
                      · {a.entries.length} page{a.entries.length === 1 ? "" : "s"}
                    </span>
                  </p>
                  {a.entries.map((e) => (
                    <ChangeRow key={`${e.source}-${e.source_id}`} entry={e} />
                  ))}
                </div>
              ))}
            </section>
          ))}
          {data?.truncated && (
            <p className="font-sans text-[11px] text-muted mt-2">
              Showing the available history — earlier changes may not be listed.
            </p>
          )}
        </div>

        {data && total > 0 && (
          <div className="px-6 py-4 border-t border-hair">
            <Button
              variant="primary"
              className="w-full justify-center"
              disabled={
                data.compile_running || data.harvest_running || startCompile.isPending
              }
              onClick={() => startCompile.mutate({})}
            >
              <Sparkles size={14} strokeWidth={1.5} />
              {data.compile_running
                ? "Compiling…"
                : data.harvest_running
                  ? "Waiting for harvest…"
                  : "Compile these into your map"}
            </Button>
          </div>
        )}
      </div>
    </SideDrawer>
  );
}
