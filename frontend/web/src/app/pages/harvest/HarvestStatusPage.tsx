import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Sparkles, Trash2, X } from "lucide-react";
import { PageShell } from "../../layouts/PageShell";
import { Button } from "../../components/ui/Button";
import { AlertDialog } from "../../components/ui/AlertDialog";
import { Dialog, DialogClose } from "../../components/ui/Dialog";
import { HarvestProgressBar, EtaEstimateMarker } from "../../components/HarvestProgressBar";
import { LiveLogTail } from "../../components/LiveLogTail";
import { CompletionSummary } from "../../components/CompletionSummary";
import { HarvestHistoryList } from "../../components/HarvestHistoryList";
import { BuildSectionTabs } from "../../components/BuildSectionTabs";
import {
  useHarvestCurrent,
  useHarvestHistory,
  useCancelHarvest,
  useResetHarvest,
  useStartHarvest,
  type HarvestStatus,
  type SourceProgress,
} from "../../api/harvest";
import { useConnections } from "../../api/connections";
import { useHarvestStream } from "../../sse/useHarvestStream";
import { computeBytesEtaSeconds, computeEtaSeconds, formatEta } from "../../lib/formatEta";

// Mirror of the per-source overlay set in HarvestProgressBar — sources whose
// per-doc cost varies enough that docs/sec is a misleading ETA signal.
const BYTES_WEIGHTED_ETA_SOURCES = new Set(["notion"]);
import { useSmoothEta } from "../../lib/useSmoothEta";

/** What badge a source's progress card should show: prefer the backend's
 *  terminal status, otherwise derive listing/running/complete from counts. */
function sourceDisplayStatus(
  p: SourceProgress,
): "listing" | "running" | "complete" | "failed" | "cancelled" {
  if (p.status === "complete" || p.status === "failed" || p.status === "cancelled") {
    return p.status;
  }
  if ((p.total || 0) === 0) return "listing";
  if ((p.done || 0) >= p.total) return "complete";
  return "running";
}

export function HarvestStatusPage() {
  const navigate = useNavigate();
  const current = useHarvestCurrent({ poll: true });
  const polledStatus: HarvestStatus = current.data?.status ?? "idle";
  // Open SSE when we believe a harvest is running (according to either source).
  const stream = useHarvestStream(polledStatus === "running");
  // Stream wins while connected; otherwise fall back to the polled snapshot.
  const status: HarvestStatus = stream.connected ? stream.status : polledStatus;
  const perSource: Record<string, SourceProgress> = stream.connected
    ? stream.perSource
    : current.data?.sources ?? {};
  const summary = stream.connected ? stream.summary : current.data?.summary ?? null;

  const cancel = useCancelHarvest();
  const reset = useResetHarvest();
  const start = useStartHarvest();
  const history = useHarvestHistory();
  const connections = useConnections();
  const connectedCount =
    connections.data?.filter((c) => c.status === "connected").length ?? 0;
  const [resetOpen, setResetOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);

  const { totalDone, totalTarget, polledTotalRate, slowestEtaSeconds } = useMemo(() => {
    let done = 0;
    let target = 0;
    let rate = 0;
    let hasRate = false;
    let slowest: number | null = null;
    Object.entries(perSource).forEach(([src, p]) => {
      done += p.done;
      target += p.total;
      if (typeof p.rate === "number") {
        rate += p.rate;
        hasRate = true;
      }
      // The headline ETA is the *slowest* source's remaining time — the run
      // isn't done until the last one finishes. Sources that have completed
      // (or were cancelled / failed) don't contribute.
      const isTerminal =
        p.status === "complete" || p.status === "failed" || p.status === "cancelled";
      if (!isTerminal && p.total > 0) {
        const processed = Math.min(p.total, p.done + p.skipped + p.failed);
        // Match the per-source card: use bytes-weighted ETA for Notion when
        // available, fall back to docs/sec ETA otherwise. Keeps the headline
        // consistent with the card the user is staring at.
        const bytesSecs = BYTES_WEIGHTED_ETA_SOURCES.has(src)
          ? computeBytesEtaSeconds(processed, p.total, p.bytes_rate, p.avg_bytes_per_doc)
          : null;
        const secs = bytesSecs ?? computeEtaSeconds(processed, p.total, p.rate);
        if (secs != null && (slowest === null || secs > slowest)) slowest = secs;
      }
    });
    return {
      totalDone: done,
      totalTarget: target,
      polledTotalRate: hasRate ? rate : null,
      slowestEtaSeconds: slowest,
    };
  }, [perSource]);
  // Sum the per-source rates for the "across all sources" stat. The headline
  // ETA, however, is set by the slowest active source — a fast source can't
  // pull the aggregate ETA below the time the slow one still needs.
  const totalRate = stream.connected ? stream.totalRate : polledTotalRate;
  // Smooth the headline ETA so it ticks down 1s/sec between samples instead
  // of snapping when a new rate sample arrives. The hook handles null targets
  // (we feed it the computed value even outside the "running" branch — when
  // there's no target, it returns null and idles).
  const rawHeadlineEta =
    slowestEtaSeconds ?? computeEtaSeconds(totalDone, totalTarget, totalRate);
  const smoothedHeadlineEta = useSmoothEta(rawHeadlineEta);

  function handleCancel() {
    cancel.mutate(undefined, {
      onSuccess: () => toast.info("Harvest cancelled."),
      onError: (err) => toast.error("Couldn't cancel", { description: String(err) }),
    });
  }

  function handleReset() {
    reset.mutate(undefined, {
      onSuccess: () => {
        setResetOpen(false);
        toast.success("Harvested data cleared.", {
          description: "Sources and credentials are untouched — run a harvest to repopulate.",
        });
      },
      onError: (err) => toast.error("Couldn't reset", { description: String(err) }),
    });
  }

  function handleRetry() {
    start.mutate(
      { sources: null },
      {
        onError: (err) => toast.error("Couldn't start harvest", { description: String(err) }),
      },
    );
  }

  // ─── Keyboard shortcuts (B3) ─────────────────────────────────────
  // S = Start (idle), C = Cancel (running), R = Retry (failed), ? = help.
  // Mounted on document while the route is /harvest (this page only renders
  // there). Bails out when typing in a form field or holding a modifier.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      const target = event.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName;
        if (
          tag === "INPUT" ||
          tag === "TEXTAREA" ||
          tag === "SELECT" ||
          target.isContentEditable
        ) {
          return;
        }
      }

      // `?` always shows the help overlay (works regardless of state).
      if (event.key === "?") {
        event.preventDefault();
        setShortcutsOpen((open) => !open);
        return;
      }

      // While the help overlay is open, swallow other single-key shortcuts so
      // the user can read it without accidentally firing Cancel etc.
      if (shortcutsOpen) return;

      const key = event.key.toLowerCase();
      if (key === "s") {
        // Start: idle or failed (no in-page Start button exists — mirror the
        // visible primary CTA which navigates to /build/sources).
        if (status === "idle" && !reset.isPending) {
          event.preventDefault();
          navigate("/build/sources");
        }
      } else if (key === "c") {
        // Cancel: only valid while a harvest is running.
        if (status === "running" && !cancel.isPending) {
          event.preventDefault();
          handleCancel();
        }
      } else if (key === "r") {
        // Retry: re-run a harvest after a failure.
        if (status === "failed" && !start.isPending) {
          event.preventDefault();
          handleRetry();
        }
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, shortcutsOpen, cancel.isPending, reset.isPending, start.isPending]);

  // ─── State branches ──────────────────────────────────────────────

  if (status === "running") {
    // Smoothed ETA (see useSmoothEta) — falls back to the raw computation
    // for the first frame before the smoother has a sample to interpolate.
    const totalEta = smoothedHeadlineEta ?? rawHeadlineEta;
    return (
      <>
      <PageShell
        eyebrow={
          <span className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-sage animate-pulse" aria-hidden />
            Harvesting now
          </span>
        }
        title="Harvesting"
        description={
          stream.connected
            ? "Live updates streaming as the harvester picks up documents."
            : "Connecting to the live event stream…"
        }
        actions={
          <Button variant="secondary" onClick={handleCancel} disabled={cancel.isPending}>
            <X size={14} strokeWidth={1.5} />
            Cancel harvest
          </Button>
        }
        tabs={<BuildSectionTabs />}
      >
        <section className="grid grid-cols-[repeat(auto-fit,minmax(min(180px,100%),1fr))] gap-4 mb-8">
          <BigStat
            label="Harvested"
            value={totalDone.toLocaleString()}
            sub={totalTarget > 0 ? `of ${totalTarget.toLocaleString()}` : undefined}
          />
          <BigStat
            label="Rate"
            value={totalRate != null ? `${totalRate.toFixed(1)}/s` : "—"}
            sub="across all sources"
          />
          <BigStat
            label="ETA"
            value={
              totalEta != null ? (
                <span className="inline-flex items-baseline gap-1">
                  <EtaEstimateMarker />
                  {formatEta(totalEta)}
                </span>
              ) : (
                formatEta(totalEta)
              )
            }
            sub={
              totalTarget > 0
                ? `slowest source · ${(totalTarget - totalDone).toLocaleString()} remaining`
                : undefined
            }
          />
          <BigStat
            label="Sources"
            value={Object.values(perSource)
              .filter((p) => {
                const s = sourceDisplayStatus(p);
                return s === "running" || s === "listing";
              })
              .length.toString()}
            sub={`active${
              Object.keys(perSource).length ? ` · ${Object.keys(perSource).length} total` : ""
            }`}
          />
        </section>

        {Object.keys(perSource).length > 0 && (
          <section className="grid grid-cols-[repeat(auto-fit,minmax(min(360px,100%),1fr))] gap-4 mb-8">
            {Object.entries(perSource).map(([source, prog]) => (
              <HarvestProgressBar
                key={source}
                source={source}
                progress={prog}
                status={sourceDisplayStatus(prog)}
              />
            ))}
          </section>
        )}

        <section>
          <p className="eyebrow mb-3">Live log</p>
          <LiveLogTail entries={stream.logs} height={420} />
        </section>
      </PageShell>
      <ShortcutsDialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
      </>
    );
  }

  if ((status === "complete" || status === "cancelled") && summary) {
    return (
      <>
      <PageShell
        title={status === "cancelled" ? "Harvest cancelled" : "Harvest complete"}
        tabs={<BuildSectionTabs />}
      >
        <CompletionSummary
          summary={summary}
          perSource={perSource}
          cancelled={status === "cancelled"}
        />
      </PageShell>
      <ShortcutsDialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
      </>
    );
  }

  // idle (with or without history) — also covers `failed`, which falls through.
  const runs = history.data?.runs ?? [];
  const hasSources = connectedCount > 0;

  function handleStartHarvest() {
    start.mutate(
      { sources: null },
      {
        onSuccess: () =>
          toast.success(`Harvesting ${connectedCount} source${connectedCount === 1 ? "" : "s"}…`),
        onError: (err) => toast.error("Couldn't start harvest", { description: String(err) }),
      },
    );
  }

  return (
    <>
    <PageShell
      title={runs.length === 0 ? "No harvests yet" : "Harvest history"}
      description={
        runs.length === 0
          ? hasSources
            ? "You've connected sources but haven't run a harvest yet — start one to populate Mnemify."
            : "Once you connect a source and run a harvest, you'll see live progress and a per-run history here."
          : `${runs.length} recorded run${runs.length === 1 ? "" : "s"}.`
      }
      actions={
        <>
          {runs.length > 0 && (
            <Button
              variant="ghost"
              onClick={() => setResetOpen(true)}
              disabled={reset.isPending}
            >
              <Trash2 size={14} strokeWidth={1.5} />
              Reset harvested data
            </Button>
          )}
          {hasSources ? (
            <Button variant="primary" onClick={handleStartHarvest} disabled={start.isPending}>
              <Sparkles size={14} strokeWidth={1.5} />
              Run a harvest
            </Button>
          ) : (
            <Button variant="primary" onClick={() => navigate("/build/sources")}>
              <Sparkles size={14} strokeWidth={1.5} />
              Connect a source
            </Button>
          )}
        </>
      }
      tabs={<BuildSectionTabs />}
    >
      <HarvestHistoryList runs={runs} />
      <AlertDialog
        open={resetOpen}
        onOpenChange={setResetOpen}
        title="Reset harvested data?"
        description={
          <>
            Deletes every harvested document, the harvest manifest + log, and the
            compiled map under <code className="font-mono text-xs">.mnemify/</code>.
            Your source connections and credentials are <strong>not</strong> touched —
            run a harvest again to repopulate. This can't be undone.
          </>
        }
        confirmLabel="Reset everything"
        cancelLabel="Keep it"
        tone="destructive"
        onConfirm={handleReset}
        confirming={reset.isPending}
      />
    </PageShell>
    <ShortcutsDialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
    </>
  );
}

function BigStat({
  label,
  value,
  sub,
}: {
  label: string;
  value: ReactNode;
  sub?: string;
}) {
  return (
    <div className="bg-bone/40 border border-hair rounded-2xl p-5">
      <p className="eyebrow mb-1.5">{label}</p>
      <p className="font-serif text-3xl text-ink tabular-nums leading-none">{value}</p>
      {sub && <p className="font-sans text-xs text-muted mt-2">{sub}</p>}
    </div>
  );
}

/** Help overlay for the page's keyboard shortcuts (B3). Opened by `?`. */
function ShortcutsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const rows: Array<{ key: string; label: string; hint: string }> = [
    { key: "S", label: "Start a harvest", hint: "When idle" },
    { key: "C", label: "Cancel the current harvest", hint: "While running" },
    { key: "R", label: "Retry the last harvest", hint: "After a failure" },
    { key: "?", label: "Toggle this help", hint: "Anywhere on this page" },
  ];
  return (
    <Dialog open={open} onOpenChange={onOpenChange} width="440px" ariaLabel="Keyboard shortcuts">
      <div className="relative p-6">
        <DialogClose onClose={() => onOpenChange(false)} />
        <p className="eyebrow mb-1.5">Keyboard</p>
        <h2 className="font-serif text-2xl text-ink leading-tight mb-4">Shortcuts</h2>
        <ul className="space-y-2.5">
          {rows.map((row) => (
            <li key={row.key} className="flex items-center justify-between gap-4">
              <div className="flex flex-col">
                <span className="font-sans text-sm text-ink">{row.label}</span>
                <span className="font-sans text-xs text-muted">{row.hint}</span>
              </div>
              <kbd className="inline-flex items-center justify-center min-w-[1.75rem] px-2 h-[1.5rem] rounded-md border border-hair bg-bone/80 font-mono text-xs text-ink/80">
                {row.key}
              </kbd>
            </li>
          ))}
        </ul>
        <p className="font-sans text-[11px] text-muted mt-5">
          Shortcuts are ignored while typing in a field or holding <kbd className="font-mono">⌘</kbd>/<kbd className="font-mono">Ctrl</kbd>.
        </p>
      </div>
    </Dialog>
  );
}
