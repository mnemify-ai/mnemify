import { SourceBadge, sourceMeta } from "./SourceBadge";
import { Badge } from "./ui/Badge";
import { Tooltip } from "./ui/Tooltip";
import {
  computeBytesEtaSeconds,
  computeEtaSeconds,
  formatEta,
} from "../lib/formatEta";
import { cn } from "../lib/cn";
import type { SourceProgress } from "../api/harvest";

// Sources whose per-doc cost varies by orders of magnitude — Notion pages
// can range from a few KB (a stub) to many MB (a doc with deep block
// trees + paginated comments). For these we prefer the bytes-projected
// ETA, which doesn't visibly stall when a heavy doc lands. Other sources
// (Confluence pages, Obsidian files, Jira issues) are uniform enough that
// docs/sec is just as good — and the bytes-projected version would only
// add latency without insight.
const BYTES_WEIGHTED_ETA_SOURCES = new Set(["notion"]);

interface HarvestProgressBarProps {
  source: string;
  progress: SourceProgress;
  status: "listing" | "running" | "complete" | "failed" | "cancelled";
}

// Left-rule color per stage status. The card carries a 3px left border that
// colors-by-status so the eye can scan vertically through a stack of sources
// without parsing the badge first.
const STATUS_LEFT_RULE: Record<HarvestProgressBarProps["status"], string> = {
  listing: "border-l-hair",
  running: "border-l-magenta",
  complete: "border-l-success",
  failed: "border-l-danger",
  cancelled: "border-l-muted",
};

export function HarvestProgressBar({ source, progress, status }: HarvestProgressBarProps) {
  const total = progress.total || 0;
  const done = progress.done || 0;
  const skipped = progress.skipped || 0;
  const failed = progress.failed || 0;
  // "Processed" = anything the harvester is done deciding on (succeeded,
  // skipped, or failed). The visual bar tracks processed/total so a run with
  // many skips still reaches 100% when the source is complete.
  const processed = Math.min(total, done + skipped + failed);
  const percent =
    status === "complete" ? 100 : total > 0 ? Math.min(100, (processed / total) * 100) : 0;
  // ETA tracks remaining work in the "still trying" sense — already-skipped /
  // failed items aren't waiting on throughput, so exclude them too.
  // For variable-cost sources (Notion) we prefer the bytes-projected ETA,
  // and fall back to the docs/sec one while bytes_rate is warming up.
  const docsEta = computeEtaSeconds(processed, total, progress.rate);
  const bytesEta = BYTES_WEIGHTED_ETA_SOURCES.has(source)
    ? computeBytesEtaSeconds(
        processed,
        total,
        progress.bytes_rate,
        progress.avg_bytes_per_doc,
      )
    : null;
  const eta = bytesEta ?? docsEta;

  // Screen-reader label — the visual layout below is dot/number soup.
  const label = sourceMeta(source).label;
  const rateText = progress.rate != null ? `, ${progress.rate.toFixed(1)} per second` : "";
  const etaText =
    (status === "running" || status === "listing") && eta != null
      ? `, ETA ${formatEta(eta)}`
      : "";
  const stateText =
    status === "complete" ? ", complete"
    : status === "failed" ? ", failed"
    : status === "cancelled" ? ", cancelled"
    : "";
  const ariaLabel =
    total > 0
      ? `${label}: ${done} of ${total} documents harvested${rateText}${etaText}${stateText}`
      : `${label}: listing documents${rateText}`;

  return (
    <div
      className={cn(
        "bg-bone/40 border border-hair rounded-2xl p-5 border-l-[3px]",
        STATUS_LEFT_RULE[status],
      )}
      role="status"
      aria-live="polite"
      aria-label={ariaLabel}
    >
      <header className="flex items-center justify-between gap-4 mb-3">
        <SourceBadge source={source} />
        <StatusPill status={status} />
      </header>

      <div className="relative h-1.5 bg-line/10 rounded-full overflow-hidden mb-3">
        <div
          className={cn(
            "absolute inset-y-0 left-0 rounded-full transition-[width] duration-500",
            status === "failed" ? "bg-rose" : status === "complete" ? "bg-sage" : "bg-magenta",
          )}
          style={{ width: `${percent}%` }}
        />
      </div>

      <div className="flex items-baseline justify-between gap-4 font-mono text-xs text-muted tabular-nums">
        <span>
          <span className="text-ink">{done.toLocaleString()}</span>
          {total > 0 && (
            <>
              {" / "}
              {total.toLocaleString()}
              {progress.already_harvested > 0 && (
                <span className="ml-2 text-muted/70">
                  · {progress.already_harvested.toLocaleString()} cached
                </span>
              )}
            </>
          )}
        </span>
        <span className="flex items-center gap-3">
          <span>
            {progress.rate != null
              ? `${progress.rate.toFixed(1)}/s`
              : status === "running" || status === "listing"
                ? "calculating…"
                : "—"}
          </span>
          {(status === "running" || status === "listing") && (
            <span>
              ETA <EtaEstimateMarker /> {formatEta(eta)}
            </span>
          )}
        </span>
      </div>

      {(progress.failed > 0 || progress.skipped > 0) && (
        <div className="flex items-center gap-3 mt-3 pt-3 border-t border-hair font-sans text-[11px]">
          {progress.failed > 0 && (
            <span className="text-rose">{progress.failed} failed</span>
          )}
          {progress.skipped > 0 && (
            <span className="text-muted">{progress.skipped} skipped</span>
          )}
        </div>
      )}
    </div>
  );
}

/** A tilde marker rendered next to an ETA to indicate the value is estimated
 *  from a smoothed (EWMA) throughput sample and will refine as the run
 *  progresses. The marker is keyboard-focusable so screen-reader / keyboard
 *  users can read the tooltip (B2 a11y rule). Delivered via the project's
 *  Radix-powered Tooltip primitive, which handles hover + focus + dismissable
 *  states. The button is focusable so keyboard users can read it too. */
export function EtaEstimateMarker() {
  return (
    <Tooltip content="Estimated from typical throughput; will update once we measure your run.">
      <button
        type="button"
        aria-label="Estimated from typical throughput; will update once we measure your run."
        className="cursor-help font-mono text-muted/80 underline decoration-dotted decoration-muted/40 underline-offset-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-magenta/40 rounded-sm"
      >
        ~
      </button>
    </Tooltip>
  );
}

function StatusPill({ status }: { status: HarvestProgressBarProps["status"] }) {
  if (status === "listing")
    return (
      <Badge tone="muted">
        <span className="h-1.5 w-1.5 rounded-full bg-muted animate-pulse" aria-hidden />
        Listing…
      </Badge>
    );
  if (status === "running")
    return (
      <Badge tone="magenta">
        <span className="h-1.5 w-1.5 rounded-full bg-magenta animate-pulse" aria-hidden />
        Harvesting
      </Badge>
    );
  if (status === "complete")
    return (
      <Badge tone="sage">
        <span className="h-1.5 w-1.5 rounded-full bg-sage" aria-hidden />
        Complete
      </Badge>
    );
  if (status === "failed") return <Badge tone="rose">Failed</Badge>;
  return <Badge tone="muted">Cancelled</Badge>;
}
