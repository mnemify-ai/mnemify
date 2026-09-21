import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { useHarvestCurrent } from "../api/harvest";
import { useStartCompile, useTerrainCurrent, useTerrainReport } from "../api/terrain";
import { totalChanges, useChanges } from "../api/changes";
import { relativeTime } from "../lib/relativeTime";
import { computeEtaSeconds, formatEta } from "../lib/formatEta";
import {
  PHASE_COUNT,
  PHASE_LABEL,
  countsFromSnapshot,
  enrichCountLine,
  phaseNumber,
  stageLabel,
  weightedPercent,
} from "../lib/compileProgress";
import { toastError, toastSuccess } from "../lib/toast";
import { Popover } from "./ui/Popover";
import { RecentChangesPanel } from "./RecentChangesPanel";
import { cn } from "../lib/cn";

/**
 * One TopBar pill for all pipeline state — replaces the four separate pills
 * (harvest progress, compile progress, pending changes, last compiled) that
 * competed for TopBar space. The pill face shows the single most urgent
 * fact (compiling > harvesting > N changed > compiled X ago); the popover
 * has the full picture plus the "Compile now" action.
 *
 * While something is running the face doubles as a progress bar: a tinted fill
 * behind the label, a human stage line with live counts, and an ETA — so a run
 * stays legible from any route, not just the Build pages.
 */
export function OpsPill() {
  const [open, setOpen] = useState(false);
  const [changesOpen, setChangesOpen] = useState(false);
  const harvest = useHarvestCurrent({ poll: true });
  const compile = useTerrainCurrent({ poll: true });
  const report = useTerrainReport();
  const changes = useChanges();
  const startCompile = useStartCompile();

  const harvesting = harvest.data?.status === "running";
  const compiling = compile.data?.status === "running";
  // A failed compile outranks "N changed" / "Compiled X ago": the face would
  // otherwise report the *previous* good build as if nothing had happened.
  const compileFailed = compile.data?.status === "failed";
  const pending = changes.data ? totalChanges(changes.data.summary) : 0;
  const compiledAt = report.data?.exists ? report.data.generated_at : null;

  // Nothing to say (fresh install, nothing running) → no pill.
  if (!harvesting && !compiling && !compileFailed && pending === 0 && !compiledAt) return null;

  let done = 0;
  let total = 0;
  // Summed docs/sec across the running sources — each source reports its own
  // EWMA rate, and they harvest concurrently, so the sum is the fleet rate.
  let harvestRate = 0;
  const sources = harvest.data ? Object.entries(harvest.data.sources) : [];
  sources.forEach(([, p]) => {
    done += p.done;
    total += p.total;
    if (p.rate && p.rate > 0) harvestRate += p.rate;
  });

  const harvestPct = total > 0 ? Math.min(100, (done / total) * 100) : 0;
  // Guard on total: before the sources finish listing it's 0, and
  // computeEtaSeconds would read that as "nothing remaining" → a bogus ~0s.
  const harvestEta = total > 0 ? computeEtaSeconds(done, total, harvestRate) : null;

  // The poll snapshot speaks snake_case; widen it once and reuse for both the
  // weighted bar and the stage line (identical maths to the Compiling page).
  const compileCounts = countsFromSnapshot(compile.data?.counts);
  const compileStage = compile.data?.stage ?? null;
  const compilePct = weightedPercent(compileStage, compileCounts);
  // Only enrich exposes a rate + a done/total worth projecting from; the other
  // phases are short enough that a made-up ETA would be worse than none.
  const compileEta =
    compileStage === "enrich" && compileCounts.enrichTotal > 0
      ? computeEtaSeconds(
          compileCounts.enrichDone,
          compileCounts.enrichTotal,
          compile.data?.counts?.rate_per_sec,
        )
      : null;

  const compileLine =
    stageLabel(compileStage, compileCounts) +
    (compileEta != null ? ` · ~${formatEta(compileEta)}` : "");
  const harvestLine =
    `Harvesting ${done.toLocaleString()}${total > 0 ? ` / ${total.toLocaleString()}` : ""}` +
    (harvestEta != null ? ` · ~${formatEta(harvestEta)}` : "");

  // The fill only makes sense while something is actually advancing.
  const facePct = compiling ? compilePct : harvesting ? harvestPct : null;

  const face = compiling ? (
    <>
      <Dot className="relative bg-magenta animate-pulse motion-reduce:animate-none" />
      <span className="relative tabular-nums">{compileLine}</span>
    </>
  ) : harvesting ? (
    <>
      <Dot className="relative bg-sage animate-pulse motion-reduce:animate-none" />
      <span className="relative tabular-nums">{harvestLine}</span>
    </>
  ) : compileFailed ? (
    <>
      <Dot className="relative bg-rose" />
      <span className="relative text-rose">Compile failed</span>
    </>
  ) : pending > 0 ? (
    <>
      <Dot className="relative bg-warning" />
      <span className="relative">{pending.toLocaleString()} changed</span>
    </>
  ) : (
    <>
      <Dot className="relative bg-sage" />
      <span className="relative">Compiled {relativeTime(compiledAt!)}</span>
    </>
  );

  // The trigger stays a plain button (a `role="progressbar"` here would cost
  // the popover its semantics) — the numbers ride along in the label instead.
  const faceAriaLabel = compiling
    ? `Pipeline status — ${compileLine}, ${Math.round(compilePct)}% complete`
    : harvesting
      ? `Pipeline status — ${harvestLine}${total > 0 ? `, ${Math.round(harvestPct)}% complete` : ""}`
      : "Pipeline status";

  const compilePhaseLine = compileStage
    ? `${phaseNumber(compileStage) ? `Phase ${phaseNumber(compileStage)} of ${PHASE_COUNT} · ` : ""}${PHASE_LABEL[compileStage] ?? compileStage}`
    : null;
  const compileCountLine = compileStage === "enrich" ? enrichCountLine(compileCounts) : null;

  const compileNow = () => {
    startCompile.mutate(
      {},
      {
        onSuccess: (res) => {
          if (res.ok) toastSuccess("Compiling your map…");
          else if (!res.dismissed) toastError("Couldn't start compile", { description: res.reason });
        },
        onError: (err) => toastError("Couldn't start compile", { description: String(err) }),
      },
    );
    setOpen(false);
  };

  return (
    <>
      <Popover
        open={open}
        onOpenChange={setOpen}
        side="bottom"
        align="end"
        trigger={
          <button
            type="button"
            aria-label={faceAriaLabel}
            className={cn(
              "relative overflow-hidden inline-flex items-center gap-2 px-3 py-1.5 rounded-full",
              "border border-hair bg-bone/40 hover:bg-bone",
              "font-sans text-xs text-muted hover:text-ink transition-colors",
            )}
          >
            {facePct !== null && (
              <span
                aria-hidden
                className="absolute inset-y-0 left-0 bg-sage/15 transition-[width] duration-slow ease-out"
                style={{ width: `${facePct}%` }}
              />
            )}
            {face}
          </button>
        }
      >
        <div className="w-72 p-3 font-sans text-sm">
          <StatusRow
            label="Harvest"
            value={
              harvesting
                ? `Running — ${done.toLocaleString()}${total > 0 ? ` / ${total.toLocaleString()}` : ""} pages${
                    harvestEta != null ? ` · ~${formatEta(harvestEta)}` : ""
                  }`
                : "Idle"
            }
            live={harvesting}
            percent={harvesting && total > 0 ? harvestPct : null}
          >
            {harvesting && sources.length > 0 && (
              <ul className="mt-1.5 space-y-0.5">
                {sources.map(([name, p]) => (
                  <li
                    key={name}
                    className="flex items-baseline justify-between gap-3 text-[11px] text-muted"
                  >
                    <span className="truncate">{name}</span>
                    <span className="shrink-0 tabular-nums">
                      {p.done.toLocaleString()}
                      {p.total > 0 && ` / ${p.total.toLocaleString()}`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </StatusRow>
          <StatusRow
            label="Compile"
            value={
              compiling
                ? `Running — ${Math.round(compilePct)}%${
                    compileEta != null ? ` · ~${formatEta(compileEta)}` : ""
                  }`
                : compileFailed
                  ? "Failed — see Build → Compile"
                  : compiledAt
                  ? `Compiled ${relativeTime(compiledAt)}`
                  : "Never compiled"
            }
            live={compiling}
            percent={compiling ? compilePct : null}
          >
            {compiling && compilePhaseLine && (
              <p className="mt-1.5 text-[11px] text-muted">{compilePhaseLine}</p>
            )}
            {compiling && compileCountLine && (
              <p className="mt-0.5 text-[11px] text-muted tabular-nums">{compileCountLine}</p>
            )}
            {compileFailed && compile.data?.error && (
              <p className="mt-1.5 font-mono text-[11px] text-rose break-words line-clamp-3">
                {compile.data.error}
              </p>
            )}
          </StatusRow>
          <StatusRow
            label="Pending changes"
            value={pending > 0 ? `${pending.toLocaleString()} pages since last compile` : "Map is up to date"}
          />
          <div className="mt-3 flex items-center gap-2 border-t border-hair pt-3">
            {(pending > 0 || compileFailed) && !compiling ? (
              <>
                <button
                  type="button"
                  onClick={compileNow}
                  disabled={startCompile.isPending}
                  className="rounded-full bg-ink px-3 py-1.5 text-xs text-cream hover:opacity-90 disabled:opacity-50"
                >
                  Compile now
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setChangesOpen(true);
                    setOpen(false);
                  }}
                  className="rounded-full border border-hair px-3 py-1.5 text-xs text-muted hover:text-ink"
                >
                  See what changed
                </button>
              </>
            ) : null}
            <Link
              to="/build/harvest"
              onClick={() => setOpen(false)}
              className="ml-auto inline-flex items-center gap-1 text-xs text-muted hover:text-ink"
            >
              Open Build
              <ArrowRight size={12} strokeWidth={1.75} aria-hidden />
            </Link>
          </div>
        </div>
      </Popover>
      <RecentChangesPanel open={changesOpen} onOpenChange={setChangesOpen} />
    </>
  );
}

function Dot({ className }: { className?: string }) {
  return <span className={cn("h-1.5 w-1.5 rounded-full", className)} aria-hidden />;
}

function StatusRow({
  label,
  value,
  live,
  percent,
  children,
}: {
  label: string;
  value: string;
  live?: boolean;
  /** 0..100 → renders a thin track under the row. Omit/null for no bar. */
  percent?: number | null;
  /** Row-specific detail (per-source lines, the compile phase line). */
  children?: ReactNode;
}) {
  return (
    <div className="py-1">
      <div className="flex items-baseline justify-between gap-3">
        <span className="shrink-0 text-[11px] uppercase tracking-wide text-muted">{label}</span>
        <span className={cn("text-right text-xs", live ? "text-ink" : "text-muted")}>{value}</span>
      </div>
      {percent != null && (
        <div
          className="mt-1.5 h-1 rounded-full bg-line/[0.22] overflow-hidden"
          role="progressbar"
          aria-label={`${label} progress`}
          aria-valuenow={Math.round(percent)}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className={cn(
              "h-full rounded-full transition-[width] duration-slow ease-out",
              live ? "bg-sage" : "bg-muted/40",
            )}
            style={{ width: `${percent}%` }}
          />
        </div>
      )}
      {children}
    </div>
  );
}
