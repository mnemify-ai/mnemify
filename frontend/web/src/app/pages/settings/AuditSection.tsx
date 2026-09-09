import { useState } from "react";
import { Button } from "../../components/ui/Button";
import { SettingsSection } from "./SettingsSection";
import { useAuditLog, type AuditEntry } from "../../api/audit";
import { relativeTime } from "../../lib/relativeTime";
import { cn } from "../../lib/cn";

const ACTION_LABELS: Record<string, string> = {
  harvest_started: "Harvest started",
  harvest_completed: "Harvest completed",
  harvested: "Document harvested",
  skipped: "Document skipped",
  harvest_failed: "Harvest failed",
  deleted_at_source: "Deleted at source",
  attachment_downloaded: "Attachment downloaded",
};

const ACTION_TONE: Record<string, string> = {
  harvest_failed: "text-rose",
  deleted_at_source: "text-muted",
  skipped: "text-muted",
  harvest_completed: "text-sage",
  harvest_started: "text-magenta",
};

const PAGE_SIZE = 100;

export function AuditSection() {
  const [action, setAction] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  const { data, isLoading, isError, error, refetch } = useAuditLog({
    offset,
    limit: PAGE_SIZE,
    action: action ?? undefined,
  });

  const total = data?.total ?? 0;
  const entries = data?.entries ?? [];
  const knownActions = data?.actions ?? Object.keys(ACTION_LABELS);
  const pageStart = entries.length === 0 ? 0 : offset + 1;
  const pageEnd = offset + entries.length;
  const hasPrev = offset > 0;
  const hasNext = offset + entries.length < total;

  return (
    <div className="max-w-5xl">
      <SettingsSection
        eyebrow="Activity"
        title="Audit log"
        help={
          <>
            Every harvest, skip, failure, and deletion — appended to{" "}
            <code className="font-mono text-[11px]">.mnemify/harvest-log.jsonl</code>{" "}
            and surfaced here. Useful for debugging a run, or just keeping an eye on what
            Mnemify has been up to.
          </>
        }
      >
        <div className="flex flex-wrap items-center gap-2 mb-5" role="group" aria-label="Filter by action">
            <FilterChip
              active={action === null}
              onClick={() => {
                setAction(null);
                setOffset(0);
              }}
              label="All"
            />
            {knownActions.map((a) => (
              <FilterChip
                key={a}
                active={action === a}
                onClick={() => {
                  setAction(a);
                  setOffset(0);
                }}
                label={ACTION_LABELS[a] ?? a}
              />
            ))}
          </div>

          {isLoading ? (
            <p className="font-sans text-sm text-muted animate-pulse motion-reduce:animate-none py-8 text-center">
              Loading…
            </p>
          ) : isError ? (
            <div className="py-8 text-center">
              <p className="font-sans text-sm text-rose mb-3">
                Couldn't load the audit log{error instanceof Error ? `: ${error.message}` : ""}.
              </p>
              <Button variant="secondary" size="sm" onClick={() => refetch()}>
                Retry
              </Button>
            </div>
          ) : entries.length === 0 ? (
            <div className="py-12 text-center">
              <p className="font-serif text-lg text-ink mb-2">Nothing here yet</p>
              <p className="font-sans text-sm text-muted max-w-prose mx-auto">
                {action
                  ? `No entries with action "${ACTION_LABELS[action] ?? action}". Try a different filter.`
                  : "Run a harvest and your map's activity will appear here."}
              </p>
            </div>
          ) : (
            <>
              <div className="overflow-x-auto -mx-2">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="text-left font-sans text-[11px] uppercase tracking-eyebrow text-muted border-b border-hair">
                      <th className="px-2 py-2 font-medium">When</th>
                      <th className="px-2 py-2 font-medium">Action</th>
                      <th className="px-2 py-2 font-medium">Source</th>
                      <th className="px-2 py-2 font-medium">Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((e, i) => (
                      <AuditRow key={`${e.ts}-${i}`} entry={e} index={i} />
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex items-center justify-between mt-5 pt-4 border-t border-hair">
                <p className="font-sans text-xs text-muted tabular-nums">
                  {pageStart}–{pageEnd} of {total.toLocaleString()}
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                    disabled={!hasPrev}
                  >
                    ← Newer
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setOffset(offset + PAGE_SIZE)}
                    disabled={!hasNext}
                  >
                    Older →
                  </Button>
                </div>
              </div>
            </>
          )}
      </SettingsSection>
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center px-3 py-1 rounded-full text-xs font-sans transition-colors border",
        active
          ? "bg-ink text-cream border-ink"
          : "bg-bone/40 text-muted border-hair hover:bg-bone hover:text-ink",
      )}
    >
      {label}
    </button>
  );
}

function AuditRow({ entry, index }: { entry: AuditEntry; index: number }) {
  const label = ACTION_LABELS[entry.action] ?? entry.action;
  const tone = ACTION_TONE[entry.action] ?? "text-ink";
  // 30ms per-row stagger, capped at the 8th row (index 7). Beyond that, no
  // extra delay — keeps long lists from feeling sluggish on first paint.
  const staggerDelay = `${Math.min(index, 7) * 30}ms`;
  return (
    <tr
      className="border-b border-hair/60 hover:bg-bone/30 transition-colors animate-fade-in motion-reduce:animate-none"
      style={{ animationDelay: staggerDelay }}
    >
      <td className="px-2 py-2 align-top font-sans text-xs text-muted whitespace-nowrap tabular-nums">
        <span title={entry.ts}>{entry.ts ? relativeTime(entry.ts) : "—"}</span>
      </td>
      <td className={cn("px-2 py-2 align-top font-sans text-xs whitespace-nowrap", tone)}>
        {label}
      </td>
      <td className="px-2 py-2 align-top font-sans text-xs text-muted whitespace-nowrap">
        {entry.source ?? "—"}
      </td>
      <td className="px-2 py-2 align-top font-sans text-sm text-ink max-w-xl">
        {renderDetails(entry)}
      </td>
    </tr>
  );
}

function renderDetails(e: AuditEntry): React.ReactNode {
  if (e.action === "harvest_started") {
    return (
      <span className="font-sans text-muted text-xs">
        Run <code className="font-mono text-[11px]">{e.run ?? "?"}</code>
        {e.mode ? ` · ${e.mode}` : ""}
      </span>
    );
  }
  if (e.action === "harvest_completed") {
    const s = e.stats ?? {};
    return (
      <span className="font-sans text-muted text-xs tabular-nums">
        {Object.entries(s)
          .map(([k, v]) => `${k}: ${v}`)
          .join(" · ")}
      </span>
    );
  }
  if (e.action === "harvested" || e.action === "skipped" || e.action === "deleted_at_source") {
    return (
      <span>
        <span className="text-ink">{e.title ?? "—"}</span>
        {e.reason && <span className="text-muted text-xs"> · {e.reason}</span>}
      </span>
    );
  }
  if (e.action === "harvest_failed") {
    return (
      <span>
        <span className="text-ink">{e.title ?? "—"}</span>
        {e.error && <span className="text-rose text-xs"> · {e.error}</span>}
      </span>
    );
  }
  if (e.action === "attachment_downloaded") {
    return (
      <span className="text-ink">
        {e.file ?? "—"}
        {e.size != null && (
          <span className="text-muted text-xs tabular-nums"> · {formatBytes(e.size)}</span>
        )}
      </span>
    );
  }
  return <span className="text-muted text-xs">—</span>;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
