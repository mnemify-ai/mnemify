import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import { ArrowRight, Check, Clock, Flame, Sparkles, Sprout, X } from "lucide-react";
import { useStartCompile, useTerrainReport } from "../api/terrain";
import { useStartHarvest } from "../api/harvest";
import { useConnections } from "../api/connections";
import { useUpsertSchedule } from "../api/schedules";
import { qk } from "../api/keys";
import { morningUtcCron } from "../lib/cron";
import { Button } from "./ui/Button";
import { totalChanges, useChanges } from "../api/changes";
import { relativeTime } from "../lib/relativeTime";
import { hasClickedTag } from "../lib/onboardingFlags";
import {
  HARVEST_NUDGE_SNOOZE_MS,
  computeBriefing,
  computeHarvestNudge,
  computePendingLine,
} from "../lib/briefing";
import { RecentChangesPanel } from "./RecentChangesPanel";

/**
 * "What's new" — the daily-orientation card on Home. The map shows the
 * *structure* of your knowledge but never what *changed*; this fills that gap
 * from data the compile already produces (framing is compile-relative, matching
 * the gating below):
 *   • growth deltas since the previous compile (stats.deltas)
 *   • what's drawing attention right now (report.burning)
 *   • how fresh the map is (generated_at)
 *
 * Surfacing rules keep it from nagging:
 *   • only after the user's first tag-click (so it never piles onto the
 *     MapInteractionHint for brand-new users)
 *   • only when this compile hasn't been acknowledged yet (a newer compile
 *     re-opens it; dismissing marks the current one seen)
 *   • only when there's something worth saying
 */

const LAST_SEEN_KEY = "mnemify.briefing.lastSeenCompile";

function readLastSeen(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(LAST_SEEN_KEY);
  } catch {
    return null;
  }
}

function writeLastSeen(value: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LAST_SEEN_KEY, value);
  } catch {
    /* quota exceeded or storage disabled — silently noop */
  }
}

const NUDGE_SNOOZE_KEY = "mnemify.harvestNudge.snoozedUntil";

function readNudgeSnooze(): number | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(NUDGE_SNOOZE_KEY);
    const ts = raw ? Number(raw) : NaN;
    return Number.isFinite(ts) ? ts : null;
  } catch {
    return null;
  }
}

function writeNudgeSnooze(value: number): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(NUDGE_SNOOZE_KEY, String(value));
  } catch {
    /* quota exceeded or storage disabled — silently noop */
  }
}

export function BriefingCard({ onTagSelect }: { onTagSelect?: (tagId: string) => void }) {
  const { data: report } = useTerrainReport();
  const { data: changes } = useChanges();
  const startCompile = useStartCompile();
  const startHarvest = useStartHarvest();
  const upsertSchedule = useUpsertSchedule();
  const { data: connections } = useConnections();
  const qc = useQueryClient();
  const [morningEnabled, setMorningEnabled] = useState(false);
  const [ackedAt, setAckedAt] = useState<string | null>(readLastSeen);
  const [nudgeSnoozedUntil, setNudgeSnoozedUntil] = useState<number | null>(readNudgeSnooze);
  const [changesOpen, setChangesOpen] = useState(false);

  const view = computeBriefing({ report, hasClickedTag: hasClickedTag(), ackedAt });
  // Only nag about pending changes once a map exists — before the first
  // compile, MapEmptyState already owns the "compile your map" moment.
  const pendingTotal = changes && report?.exists ? totalChanges(changes.summary) : 0;
  const pendingLine = changes
    ? computePendingLine(pendingTotal, changes.changes, {
        summary: changes.summary,
        lastHarvestTime: changes.last_harvest_time,
      })
    : null;
  // Offer a harvest when the data itself is stale. Mutually exclusive with
  // the pending line: the nudge is null whenever pendingTotal > 0.
  const nudge =
    changes && report?.exists
      ? computeHarvestNudge({
          lastHarvestTime: changes.last_harvest_time,
          scheduleEnabled: changes.schedule_enabled,
          harvestRunning: changes.harvest_running,
          pendingTotal,
          snoozedUntil: nudgeSnoozedUntil,
        })
      : null;
  // Pending changes are shown even when the compile briefing was dismissed —
  // they describe what the map does NOT yet contain, so acking a compile
  // can't clear them; only compiling does.
  if (!view && !pendingLine && !nudge) return null;
  const { compiledAt, deltaChips, burning } = view ?? {
    compiledAt: null,
    deltaChips: [],
    burning: [],
  };

  const dismiss = () => {
    if (!compiledAt) return;
    writeLastSeen(compiledAt);
    setAckedAt(compiledAt);
  };

  // "Enable morning harvest": one daily schedule per connected source. The
  // backend has no bulk endpoint, so fan out and treat any failure as a whole.
  const enableMorningHarvest = async () => {
    const sources = (connections ?? [])
      .filter((c) => c.status === "connected")
      .map((c) => c.source);
    if (sources.length === 0) {
      toast.error("Connect a source first to schedule harvests.");
      return;
    }
    const cron = morningUtcCron();
    try {
      await Promise.all(
        sources.map((source) => upsertSchedule.mutateAsync({ source, cron, enabled: true })),
      );
      setMorningEnabled(true);
      // schedule_enabled lives on the changes payload — refresh it so the
      // nudge stops suggesting a schedule on the next render.
      qc.invalidateQueries({ queryKey: qk.changes() });
    } catch (err) {
      toast.error("Couldn't enable morning harvest", { description: String(err) });
    }
  };

  return (
    <section
      role="region"
      aria-label="What's new in your knowledge map"
      className="glass-panel rounded-2xl w-[300px] max-w-[calc(100vw-2rem)] overflow-hidden shadow-sm animate-fade-in motion-reduce:animate-none"
    >
      <header className="px-4 pt-3 pb-1 flex items-start justify-between gap-2">
        <div>
          <p className="eyebrow mb-0.5">What's new</p>
          <h2 className="font-serif text-sm text-ink">
            {compiledAt
              ? `Compiled ${relativeTime(compiledAt)}`
              : pendingLine
                ? "Your map is behind"
                : "Keep your knowledge fresh"}
          </h2>
        </div>
        {view && (
          <button
            type="button"
            onClick={dismiss}
            aria-label="Dismiss briefing"
            className="text-muted hover:text-ink transition-colors -mr-1 -mt-0.5 shrink-0"
          >
            <X className="h-3.5 w-3.5" aria-hidden />
          </button>
        )}
      </header>

      <div className="px-4 pb-3">
        {pendingLine && (
          <div className="mb-1">
            <p className="font-sans text-xs text-ink">
              {pendingLine}
              <span className="text-muted"> — not on your map yet</span>
            </p>
            <div className="flex items-center gap-2 mt-1.5">
              <button
                type="button"
                onClick={() => startCompile.mutate({})}
                disabled={
                  startCompile.isPending ||
                  changes?.compile_running ||
                  changes?.harvest_running
                }
                className="inline-flex items-center gap-1 font-sans text-xs text-magenta hover:underline disabled:opacity-50 disabled:no-underline"
              >
                <Sparkles size={12} strokeWidth={1.75} aria-hidden />
                {changes?.compile_running ? "Compiling…" : "Compile now"}
              </button>
              <span className="text-hair">·</span>
              <button
                type="button"
                onClick={() => setChangesOpen(true)}
                className="font-sans text-xs text-muted hover:text-ink transition-colors"
              >
                See all changes
              </button>
            </div>
          </div>
        )}
        {nudge && (
          <div className="mb-1">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                {view && (
                  <h3 className="font-serif text-sm text-ink">Keep your knowledge fresh</h3>
                )}
                <p className="font-sans text-xs text-muted">
                  Automatically check your sources every morning.
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  const until = Date.now() + HARVEST_NUDGE_SNOOZE_MS;
                  writeNudgeSnooze(until);
                  setNudgeSnoozedUntil(until);
                }}
                aria-label="Dismiss harvest reminder for a day"
                className="text-muted hover:text-ink transition-colors shrink-0"
              >
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>

            {nudge.suggestSchedule && !morningEnabled ? (
              <>
                <Button
                  type="button"
                  size="md"
                  onClick={enableMorningHarvest}
                  loading={upsertSchedule.isPending}
                  className="w-full mt-3 h-9 text-xs rounded-xl"
                >
                  {!upsertSchedule.isPending && (
                    <Clock size={13} strokeWidth={1.75} aria-hidden />
                  )}
                  Enable morning harvest
                </Button>
                {/* The scheduler is in-process (backend/src/api/scheduler.py):
                    it only fires while the local server is up. Say so rather
                    than implying an unattended background service. */}
                <p className="font-sans text-[11px] text-muted text-center mt-1.5">
                  Runs while Mnemify is open, or catches up next time you open it
                </p>
              </>
            ) : (
              <div className="mt-3 flex items-center gap-2 font-sans text-xs">
                <span className="inline-flex items-center gap-1.5 text-success">
                  <Check size={13} strokeWidth={2} aria-hidden />
                  {morningEnabled ? "Morning harvest enabled" : "Scheduled harvest enabled"}
                </span>
                <span className="text-hair">·</span>
                <Link
                  to="/settings/schedules"
                  className="text-muted hover:text-ink transition-colors"
                >
                  Manage
                </Link>
              </div>
            )}

            <div className="flex items-center gap-2 mt-2.5">
              <button
                type="button"
                onClick={() => startHarvest.mutate({ sources: null })}
                disabled={
                  startHarvest.isPending ||
                  changes?.harvest_running ||
                  changes?.compile_running
                }
                className="inline-flex items-center gap-1 font-sans text-xs text-magenta hover:underline disabled:opacity-50 disabled:no-underline"
              >
                <Sprout size={12} strokeWidth={1.75} aria-hidden />
                {startHarvest.isPending || changes?.harvest_running
                  ? "Harvesting…"
                  : "Harvest now"}
              </button>
              <span className="text-hair">·</span>
              <span className="font-sans text-xs text-muted">
                Last harvested {relativeTime(nudge.lastHarvestTime)}
              </span>
            </div>
          </div>
        )}
        {pendingLine && deltaChips.length > 0 && (
          <p className="eyebrow mt-3 mb-1">Last compile</p>
        )}
        {deltaChips.length > 0 && (
          <p className="font-sans text-xs text-ink mb-1">
            {deltaChips.join(" · ")}
            <span className="text-muted"> since the previous compile</span>
          </p>
        )}

        {burning.length > 0 && (
          <>
            <p className="eyebrow mt-3 mb-1.5">Heating up</p>
            <ul className="flex flex-col">
              {burning.map((b) => {
                const clickable = b.type === "tag" && !!onTagSelect;
                const inner = (
                  <span className="flex items-center gap-2 min-w-0">
                    <Flame
                      size={13}
                      strokeWidth={1.75}
                      className="text-magenta shrink-0"
                      aria-hidden
                    />
                    <span className="font-sans text-sm text-ink truncate">{b.label}</span>
                  </span>
                );
                return (
                  <li key={`${b.type}:${b.id}`}>
                    {clickable ? (
                      <button
                        type="button"
                        onClick={() => onTagSelect!(b.id)}
                        aria-label={`Open ${b.label} on the map`}
                        className="group w-full text-left px-2 py-1 -mx-2 rounded-lg hover:bg-bone/60 transition-colors flex items-center justify-between gap-2"
                      >
                        {inner}
                        <ArrowRight
                          size={13}
                          strokeWidth={1.75}
                          className="text-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                          aria-hidden
                        />
                      </button>
                    ) : (
                      <span className="px-2 py-1 -mx-2 flex items-center">{inner}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>
      <RecentChangesPanel open={changesOpen} onOpenChange={setChangesOpen} />
    </section>
  );
}
