import { useState, useEffect, useMemo, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowDown, ArrowRight, Clock, ListTodo, RefreshCw, Sparkles, X } from "lucide-react";
import type { CompileLogEntry } from "../sse/useCompileStream";
import { PageShell } from "../layouts/PageShell";
import { Button } from "../components/ui/Button";
import { Card, CardContent } from "../components/ui/Card";
import { Badge } from "../components/ui/Badge";
import { AiModePicker, AiModeSummary, useCompileOverrides } from "../components/AiModePicker";
import {
  useCancelCompile,
  useStartCompile,
  useTerrainCurrent,
  useTerrainReport,
  useTerrainRuns,
  type BurningItem,
  type CompileStatus,
  type TerrainRun,
} from "../api/terrain";
import { useCompileStream, type CompileCountsState } from "../sse/useCompileStream";
import { useDocumentStats } from "../api/documents";
import { useSchedules } from "../api/schedules";
import {
  hasDismissedPostCompileNext,
  hasVisitedTodos,
  markPostCompileNextDismissed,
} from "../lib/onboardingFlags";
import { qk } from "../api/keys";
import { computeEtaSeconds, formatDuration, formatEta } from "../lib/formatEta";
import {
  PHASE_COUNT,
  PHASE_DESC,
  PHASE_LABEL,
  countsFromSnapshot,
  enrichCountLine,
  phaseNumber,
  weightedPercent,
} from "../lib/compileProgress";
import { relativeTime } from "../lib/relativeTime";
import { useMapFocusStore } from "../lib/mapFocusStore";
// Canonical attention palette, shared with the map's right panel so a
// "critical" here is the same red as a "critical" there.
import { levelColor } from "../../knowledgeMap/chrome/panelShared";
import { BuildSectionTabs } from "../components/BuildSectionTabs";
import { resumeTargetFromRuns } from "../lib/compileResume";
import { cn } from "../lib/cn";

function tagLabel(id: string): string {
  return id
    .replace(/^tag\./, "")
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function CompileReportPage() {
  const navigate = useNavigate();
  const current = useTerrainCurrent({ poll: true });
  const polledStatus: CompileStatus = current.data?.status ?? "idle";
  const stream = useCompileStream(polledStatus === "running");
  const status: CompileStatus = stream.connected ? stream.status : polledStatus;

  const qc = useQueryClient();
  const prevStatusRef = useRef<CompileStatus>(status);
  useEffect(() => {
    const prev = prevStatusRef.current;
    prevStatusRef.current = status;
    if (prev === "running" && (status === "complete" || status === "failed")) {
      qc.invalidateQueries({ queryKey: qk.terrainRuns() });
      qc.invalidateQueries({ queryKey: qk.terrainReport() });
      // The compile rewrote render-data.json + mocknotes.json. MapDataProvider
      // caches them with staleTime: Infinity, so without this the 3D map keeps
      // showing the OLD snapshot (stale tag ids/names) until a full reload.
      qc.invalidateQueries({ queryKey: qk.mapData() });
    }
  }, [status, qc]);

  const report = useTerrainReport();
  const runs = useTerrainRuns();
  const docStats = useDocumentStats();
  const startCompile = useStartCompile();
  const cancelCompile = useCancelCompile();
  const overrides = useCompileOverrides();

  const totalDocs = docStats.data?.total_documents ?? 0;

  function handleCompile(fresh = false) {
    startCompile.mutate(
      { ...overrides.payload, fresh },
      {
        onSuccess: (res) => {
          if (res.dismissed) return; // closed the local-embeddings dialog
          if (!res.ok) {
            toast.error("Couldn't start compile", { description: res.reason });
          } else {
            const engine =
              res.ai_mode === "local"
                ? "local heuristics"
                : res.ai_mode === "claude"
                  ? "Claude (subscription)"
                  : "OpenAI";
            toast.success(
              fresh ? `Recompiling from scratch with ${engine}…` : `Compiling with ${engine}…`,
            );
          }
        },
        onError: (err) => toast.error("Couldn't start compile", { description: String(err) }),
      },
    );
  }

  const resumeTarget = resumeTargetFromRuns(runs.data?.runs);

  function handleResume() {
    if (!resumeTarget) return;
    startCompile.mutate(
      { source: resumeTarget.source, ai_mode: resumeTarget.ai_mode, fresh: false },
      {
        onSuccess: (res) => {
          if (res.dismissed) return;
          if (!res.ok) {
            toast.error("Couldn't resume compile", { description: res.reason });
          } else {
            toast.success("Resuming compile — finished work is reused from cache.");
          }
        },
        onError: (err) => toast.error("Couldn't resume compile", { description: String(err) }),
      },
    );
  }

  function handleCancel() {
    cancelCompile.mutate(undefined, {
      onSuccess: () => toast.info("Compile cancelled."),
      onError: (err) => toast.error("Couldn't cancel", { description: String(err) }),
    });
  }

  // ─── running ────────────────────────────────────────────────────
  if (status === "running") {
    const counts: CompileCountsState = stream.connected
      ? stream.counts
      : countsFromSnapshot(current.data?.counts);
    const stage = stream.connected ? stream.stage : current.data?.stage ?? null;
    const eta = computeEtaSeconds(counts.enrichDone, counts.enrichTotal, stream.rate);
    const pct = weightedPercent(stage, counts);
    return (
      <PageShell
        tabs={<BuildSectionTabs />}
        eyebrow={
          <span className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-sage animate-pulse" aria-hidden />
            Compiling now
          </span>
        }
        title="Compiling"
        description={
          stream.connected
            ? "Turning your harvested documents into a navigable Knowledge Map."
            : "Connecting to the compile stream…"
        }
        actions={
          <div className="flex items-center gap-3">
            <Button variant="ghost" onClick={() => navigate("/")}>
              Run in background
              <ArrowRight size={14} strokeWidth={1.75} />
            </Button>
            <Button variant="secondary" onClick={handleCancel} disabled={cancelCompile.isPending}>
              <X size={14} strokeWidth={1.5} />
              Cancel
            </Button>
          </div>
        }
      >
        <CompilePhaseCard stage={stage} pct={pct} counts={counts} />
        <CompileFunFacts
          rate={stream.rate}
          startedAt={current.data?.started_at ?? null}
          eta={eta}
          logs={stream.logs}
        />

        <section className="mt-8">
          <p className="eyebrow mb-3">Live log</p>
          <CompileLogTail logs={stream.logs} />
        </section>
      </PageShell>
    );
  }

  // ─── loading ────────────────────────────────────────────────────
  if (report.isLoading) {
    return (
      <PageShell eyebrow="Compile" title="Compile" tabs={<BuildSectionTabs />}>
        <p className="font-sans text-muted animate-pulse">Loading…</p>
      </PageShell>
    );
  }

  // ─── no terrain → onboarding ────────────────────────────────────
  if (!report.data?.exists) {
    return (
      <PageShell
        tabs={<BuildSectionTabs />}
        eyebrow="Compile"
        title="Build your Knowledge Map"
        description="Compiling turns your harvested documents into the regions, tags, and connections you see on the map. It uses an LLM for feature extraction and naming, so it takes a little while."
      >
        <LastRunNotice
          run={runs.data?.runs?.[0]}
          resumeReason={resumeTarget?.reason ?? null}
          onResume={handleResume}
          pending={startCompile.isPending}
        />
        <Card>
          <CardContent>
            {totalDocs === 0 ? (
              <>
                <p className="font-serif text-xl text-ink mb-2">Nothing harvested yet.</p>
                <p className="font-sans text-sm text-muted mb-5 max-w-prose">
                  Connect a source and run a harvest first — there's nothing to compile until then.
                </p>
                <Button variant="primary" onClick={() => navigate("/build/harvest")}>
                  Go to Harvest
                </Button>
              </>
            ) : (
              <>
                <p className="font-serif text-xl text-ink mb-1">
                  {totalDocs.toLocaleString()} document{totalDocs === 1 ? "" : "s"} ready to compile.
                </p>
                <p className="font-sans text-sm text-muted mb-5 max-w-prose">
                  Pick how to compile, then go.
                </p>
                <AiModePicker overrides={overrides} />
                <div className="mt-5 flex items-center gap-3">
                  {resumeTarget && (
                    <Button
                      variant="primary"
                      onClick={handleResume}
                      disabled={startCompile.isPending}
                      title={`The last compile was interrupted (${resumeTarget.reason}). Resume reuses everything already extracted and embedded.`}
                    >
                      <RefreshCw size={14} strokeWidth={1.5} />
                      Resume compile
                    </Button>
                  )}
                  <Button
                    variant={resumeTarget ? "secondary" : "primary"}
                    onClick={() => handleCompile()}
                    disabled={startCompile.isPending}
                  >
                    <Sparkles size={14} strokeWidth={1.5} />
                    Compile now
                  </Button>
                </div>
              </>
            )}
          </CardContent>
        </Card>
        {(runs.data?.runs?.length ?? 0) > 0 && (
          <div className="mt-8">
            <CompileRunHistory runs={runs.data!.runs} />
          </div>
        )}
      </PageShell>
    );
  }

  // ─── terrain exists → the report ────────────────────────────────
  const r = report.data;
  const stats = r.stats;
  const hl = r.highlights;
  const aiLabel =
    r.ai_mode === "local"
      ? "local heuristics"
      : r.ai_mode === "openai"
        ? "OpenAI"
        : r.ai_mode === "claude"
          ? "Claude (subscription)"
          : null;
  return (
    <PageShell
      tabs={<BuildSectionTabs />}
      eyebrow="Compile report"
      title="Your Knowledge Map"
      description={[
        r.generated_at ? `Compiled ${relativeTime(r.generated_at)}` : "Compiled",
        aiLabel,
        r.seconds != null ? `in ${formatDuration(r.seconds)}` : null,
      ]
        .filter(Boolean)
        .join(" · ") + "."}
      actions={
        <div className="flex items-center gap-3">
          <Button variant="ghost" onClick={() => navigate("/")}>
            View your map
            <ArrowRight size={14} strokeWidth={1.75} />
          </Button>
          {resumeTarget && (
            <Button
              variant="primary"
              onClick={handleResume}
              disabled={startCompile.isPending}
              title={`The last compile was interrupted (${resumeTarget.reason}). Resume reuses everything already extracted and embedded.`}
            >
              <RefreshCw size={14} strokeWidth={1.5} />
              Resume compile
            </Button>
          )}
          <Button variant="secondary" onClick={() => handleCompile(true)} disabled={startCompile.isPending}>
            <RefreshCw size={14} strokeWidth={1.5} />
            Recompile
          </Button>
        </div>
      }
    >
      <div className="space-y-10">
        <PostCompileNext />
        <LastRunNotice
          run={runs.data?.runs?.[0]}
          resumeReason={resumeTarget?.reason ?? null}
          onResume={handleResume}
          pending={startCompile.isPending}
        />
        {/* Reporting surface, not an editor — Settings → AI & Models owns the
            saved defaults, and the pre-first-compile block above owns the
            per-run override. */}
        <AiModeSummary />

        {stats && (
          <section>
            <h2 className="font-serif text-2xl text-ink mb-4">Counts</h2>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <StatTile label="Regions" value={stats.regions} sub={`${stats.subRegionsTotal} child regions`} />
              <StatTile
                label="Tags"
                value={stats.tagsTotal}
                sub={hl?.isolatedTags?.length ? `${hl.isolatedTags.length} isolated` : "all linked"}
              />
              <StatTile label="Notes" value={stats.notes} sub={`from ${stats.sources} source${stats.sources === 1 ? "" : "s"}`} />
              <StatTile label="Sources" value={stats.sources} sub="active" />
              <StatTile label="Edges" value={stats.edges} sub="co-occurrence" />
            </div>
          </section>
        )}

        <LlmUsageSection run={r.last_run} />

        {Object.keys(r.by_source).length > 0 && (
          <section>
            <h2 className="font-serif text-2xl text-ink mb-4">By source</h2>
            <div className="flex flex-wrap gap-2">
              {Object.entries(r.by_source)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([src, n]) => (
                  <Badge key={src} tone="muted">
                    {src} · {n.toLocaleString()}
                  </Badge>
                ))}
            </div>
          </section>
        )}

        {(r.burning?.length ?? 0) > 0 && (
          <section>
            <h2 className="font-serif text-2xl text-ink mb-1">Burning items</h2>
            <p className="font-sans text-sm text-muted mb-4 max-w-prose">
              Source-grounded todos, risks, open questions, and recent changes ranked by attention score.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {r.burning!.map((item) => (
                <BurningItemCard
                  key={`${item.type}:${item.id}`}
                  item={item}
                  onOpen={() => {
                    if (item.type === "tag") {
                      navigate(`/?tag=${encodeURIComponent(item.id)}`);
                    } else {
                      // Regions aren't URL-addressable — hand the id to the map
                      // focus store, which outlives the navigation to "/".
                      useMapFocusStore.getState().setFocusRegion(item.id);
                      navigate("/");
                    }
                  }}
                />
              ))}
            </div>
          </section>
        )}

        {hl && (
          <section>
            <h2 className="font-serif text-2xl text-ink mb-1">Highlights</h2>
            <p className="font-sans text-sm text-muted mb-4 max-w-prose">
              Tags the compiler flagged as structurally important. Click a chip to inspect it on the map.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <HlColumn title="God tags" desc="Highest-degree hubs." ids={hl.godTags} labels={r.tag_labels} onPick={(id) => navigate(`/?tag=${encodeURIComponent(id)}`)} />
              <HlColumn title="Bridge tags" desc="Span multiple regions." ids={hl.bridgeTags} labels={r.tag_labels} onPick={(id) => navigate(`/?tag=${encodeURIComponent(id)}`)} />
              <HlColumn title="Trending" desc="Recently updated." ids={hl.trendingTags} labels={r.tag_labels} onPick={(id) => navigate(`/?tag=${encodeURIComponent(id)}`)} />
              <HlColumn title="Isolated" desc="No co-occurrence arcs." ids={hl.isolatedTags} labels={r.tag_labels} onPick={(id) => navigate(`/?tag=${encodeURIComponent(id)}`)} />
            </div>
          </section>
        )}

        {(runs.data?.runs?.length ?? 0) > 0 && <CompileRunHistory runs={runs.data!.runs} />}
      </div>
    </PageShell>
  );
}

// ─── helpers ──────────────────────────────────────────────────────

/**
 * One "burning item" — a region or tag the compiler flagged for attention.
 * Both types are clickable: tags are URL-addressable (`/?tag=`), regions go
 * through the map-focus store. Severity is carried by a left stripe + the
 * level chip, both painted from the canonical `levelColor` scale.
 */
function BurningItemCard({ item, onOpen }: { item: BurningItem; onOpen: () => void }) {
  const color = levelColor(item.attentionLevel);
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "group relative overflow-hidden text-left rounded-lg border border-line/25 bg-bone/35",
        "pl-5 pr-4 py-3 transition-colors hover:border-magenta/40 hover:bg-magenta/5",
      )}
    >
      {/* Severity stripe. Colour is data-derived, so it stays inline —
          `overflow-hidden` above clips it to the card's corner radius. */}
      <span
        aria-hidden
        className="absolute inset-y-0 left-0 w-1"
        style={{ background: color }}
      />
      <div className="flex items-center justify-between gap-3">
        <span className="font-serif text-base text-ink truncate">{item.label}</span>
        <span
          className="shrink-0 font-sans text-xs px-2 py-0.5 rounded-full border capitalize"
          style={{ color, borderColor: `${color}80`, background: `${color}1a` }}
        >
          {item.attentionLevel}
        </span>
      </div>
      <div className="mt-2 flex items-center gap-3 font-sans text-xs text-muted">
        <span className="rounded-full border border-line/25 bg-bone/50 px-1.5 py-0.5 text-[11px] capitalize">
          {item.type}
        </span>
        <span>{Math.round(item.attentionScore)} score</span>
        <span>{item.signalCount} signal{item.signalCount === 1 ? "" : "s"}</span>
        <span className="ml-auto inline-flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100 motion-reduce:transition-none">
          {item.type === "region" ? "View on map" : "View tag"}
          <ArrowRight size={12} strokeWidth={1.75} aria-hidden />
        </span>
      </div>
    </button>
  );
}

/**
 * The centerpiece: a single card showing the CURRENT phase in plain language,
 * with a weighted overall progress bar. It cross-fades to the next phase as the
 * compile advances (the `key={stage}` remount + `animate-fade-in`). The bar is
 * clamped monotonic so an out-of-order / reconnect SSE frame never rewinds it.
 */
function CompilePhaseCard({
  stage,
  pct,
  counts,
}: {
  stage: string | null;
  pct: number;
  counts: CompileCountsState;
}) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    setShown((prev) => Math.max(prev, pct));
  }, [pct]);

  const n = phaseNumber(stage);
  const label = stage ? PHASE_LABEL[stage] ?? stage : "Getting started";
  const desc = stage ? PHASE_DESC[stage] ?? "" : "Warming up the compiler…";

  // Phase-aware count line during enrich: extraction vs embedding.
  const enrichLine = stage === "enrich" ? enrichCountLine(counts) : null;

  return (
    <Card>
      <CardContent className="p-8">
        <div className="flex items-center gap-2 mb-4">
          <span className="h-1.5 w-1.5 rounded-full bg-magenta animate-pulse" aria-hidden />
          <span className="eyebrow">
            {n ? `Phase ${n} of ${PHASE_COUNT}` : "Preparing"}
          </span>
        </div>
        <div key={stage} className="animate-fade-in">
          <h2 className="font-serif text-4xl text-ink leading-tight mb-2">{label}</h2>
          <p className={cn("font-sans text-sm text-muted max-w-prose", enrichLine ? "mb-2" : "mb-7")}>
            {desc}
          </p>
          {enrichLine && (
            <p className="font-sans text-sm text-ink tabular-nums mb-7">{enrichLine}</p>
          )}
        </div>
        <div className="flex items-center gap-4">
          <div
            className="flex-1 h-2 rounded-full bg-bone/70 overflow-hidden"
            role="progressbar"
            aria-valuenow={Math.round(shown)}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="h-full rounded-full bg-magenta transition-[width] duration-slow ease-out"
              style={{ width: `${shown}%` }}
            />
          </div>
          <span className="font-serif text-2xl text-ink tabular-nums leading-none w-14 text-right">
            {Math.round(shown)}%
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

/** Ticking elapsed seconds since `startedAt` (epoch seconds), or null. */
function useElapsedSeconds(startedAt: number | null): number | null {
  const [now, setNow] = useState(() => Date.now() / 1000);
  // Only tick (and re-render) while there's actually a running timer to show.
  useEffect(() => {
    if (startedAt == null) return;
    setNow(Date.now() / 1000);
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, [startedAt]);
  if (startedAt == null) return null;
  return Math.max(0, now - startedAt);
}

/** Count regions/tags discovered so far from the friendly log lines. */
function countForming(logs: CompileLogEntry[]): { regions: number; tags: number } {
  let regions = 0;
  let tags = 0;
  for (const l of logs) {
    if (l.msg.startsWith("Found region:")) regions += 1;
    else if (l.msg.startsWith("Tagged:")) tags += 1;
  }
  return { regions, tags };
}

/**
 * De-emphasized secondary line: what's taking shape (regions/tags forming) plus
 * the small "fun facts" — call rate, elapsed, ETA. Not cards; just a quiet line.
 */
function CompileFunFacts({
  rate,
  startedAt,
  eta,
  logs,
}: {
  rate: number | null;
  startedAt: number | null;
  eta: number | null;
  logs: CompileLogEntry[];
}) {
  const elapsed = useElapsedSeconds(startedAt);
  const { regions, tags } = useMemo(() => countForming(logs), [logs]);

  const facts: string[] = [];
  if (rate != null) facts.push(`~${rate.toFixed(1)} insights/sec`);
  if (elapsed != null) facts.push(`${formatDuration(elapsed)} elapsed`);
  if (eta != null) facts.push(`~${formatEta(eta)} left`);

  return (
    <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-1">
      {(regions > 0 || tags > 0) && (
        <span className="font-sans text-sm text-ink tabular-nums">
          {regions} region{regions === 1 ? "" : "s"} · {tags} tag{tags === 1 ? "" : "s"} forming
        </span>
      )}
      {facts.length > 0 && (
        <span className="font-sans text-xs text-muted tabular-nums">{facts.join(" · ")}</span>
      )}
    </div>
  );
}

/** Per-stage LLM usage recorded by the compiler (run.counts.llm_usage). */
interface LlmUsageRow {
  calls: number;
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  duration_ms: number;
  cost_usd: number;
  models?: string[];
}
interface LlmUsage {
  stages: Record<string, LlmUsageRow>;
  total: LlmUsageRow;
}

function parseLlmUsage(run: TerrainRun | null | undefined): LlmUsage | null {
  if (!run?.counts) return null;
  try {
    const counts = JSON.parse(run.counts);
    const u = counts?.llm_usage;
    if (!u || typeof u !== "object" || !u.total || !(u.total.calls > 0)) return null;
    return u as LlmUsage;
  } catch {
    return null;
  }
}

const STAGE_USAGE_LABEL: Record<string, string> = {
  extract: "Chunk analysis",
  embed: "Embeddings",
  merge: "Region merger",
  name: "Naming",
  notes: "Compiled notes",
  other: "Other",
};

const compact = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n >= 10_000 ? `${Math.round(n / 1000)}k` : n.toLocaleString();

/**
 * What the last compile spent, per stage. This is the measurement behind the
 * effort / model recommendations in Settings — change one knob, compile, and
 * compare this block against the previous run.
 */
function LlmUsageSection({ run }: { run: TerrainRun | null | undefined }) {
  const usage = parseLlmUsage(run);
  if (!usage) return null;
  const t = usage.total;
  const stages = Object.entries(usage.stages).sort((a, b) => b[1].input_tokens - a[1].input_tokens);
  return (
    <section>
      <h2 className="font-serif text-2xl text-ink mb-1">LLM usage</h2>
      <p className="font-sans text-xs text-muted mb-4 max-w-prose">
        Tokens this compile actually sent and received, per stage. Cached work costs nothing and does not
        appear here — a resumed or incremental compile shows only what was new.
      </p>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-4">
        <StatTile label="Calls" value={t.calls} />
        <StatTile label="Input tokens" value={t.input_tokens} sub={t.cached_input_tokens ? `${compact(t.cached_input_tokens)} from cache` : undefined} />
        <StatTile label="Output tokens" value={t.output_tokens} sub={t.reasoning_tokens ? `${compact(t.reasoning_tokens)} reasoning` : undefined} />
        <StatTile label="Model time" value={Math.round(t.duration_ms / 1000)} sub="seconds, summed across parallel calls" />
        {t.cost_usd > 0 ? (
          <Card className="bg-cream">
            <CardContent className="p-5 pt-5">
              <p className="eyebrow mb-2">Reported cost</p>
              <p className="font-serif text-4xl text-ink tabular-nums leading-none">${t.cost_usd.toFixed(2)}</p>
              <p className="font-sans text-xs text-muted mt-2">as reported by the provider</p>
            </CardContent>
          </Card>
        ) : null}
      </div>
      <ul className="divide-y divide-hair rounded-lg border border-hair bg-bone/40">
        {stages.map(([stage, row]) => (
          <li key={stage} className="flex items-center justify-between gap-4 px-4 py-2.5">
            <div className="min-w-0">
              <span className="font-sans text-sm text-ink">{STAGE_USAGE_LABEL[stage] ?? stage}</span>
              {row.models?.length ? (
                <span className="ml-2 font-mono text-[11px] text-muted truncate">{row.models.join(", ")}</span>
              ) : null}
            </div>
            <span className="font-sans text-xs text-muted tabular-nums shrink-0">
              {row.calls.toLocaleString()} calls · {compact(row.input_tokens)} in · {compact(row.output_tokens)} out
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Banner for a most-recent compile that did not finish. A usage-limit stop
 * (and a restart / cancel) is resumable: the pipeline caches every chunk
 * feature, embedding, name and note as it goes, so Resume re-spends only the
 * unfinished remainder. Other failures show the message and point at Settings.
 */
/**
 * Post-compile "what's next" block. Two surfaces are invisible to a first-time
 * user at exactly the moment they become useful: TODOs (the deadlines the
 * compile just extracted from their documents) and Settings → Schedules
 * (harvests can run on a cron, so the map refreshes itself). Neither announces
 * itself anywhere else — TODOs is one more word in the nav, and Schedules is
 * three clicks behind an icon-only gear.
 *
 * Self-retiring: the schedules row disappears once any schedule exists, the
 * TODOs row once the user has opened that page, and the whole block once it's
 * dismissed. Nothing here nags on a return visit.
 */
function PostCompileNext() {
  const schedules = useSchedules();
  const [dismissed, setDismissed] = useState(hasDismissedPostCompileNext);
  const [todosSeen] = useState(hasVisitedTodos);

  // Hold the block back until the schedules query resolves rather than
  // flashing a "set up a schedule" prompt at someone who already has one.
  if (dismissed || schedules.isLoading) return null;
  const hasSchedule = Object.values(schedules.data?.schedules ?? {}).some((s) => s.enabled);
  const showTodos = !todosSeen;
  const showSchedules = !hasSchedule;
  if (!showTodos && !showSchedules) return null;

  return (
    <Card className="border border-hair bg-bone/30">
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="eyebrow mb-1">Next</p>
            <p className="font-serif text-lg text-ink">Now that you have a map</p>
          </div>
          <button
            type="button"
            onClick={() => {
              markPostCompileNextDismissed();
              setDismissed(true);
            }}
            aria-label="Dismiss"
            className="shrink-0 grid h-7 w-7 place-items-center rounded-full text-muted transition-colors hover:bg-bone hover:text-ink"
          >
            <X size={14} strokeWidth={1.75} aria-hidden />
          </button>
        </div>
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
          {showTodos && (
            <NextStepCard
              icon={ListTodo}
              title="Your TODOs"
              body="The compile pulled deadlines, owners, and open questions out of your documents. They're collected on the TODOs page."
              cta="Open TODOs"
              to="/action-items"
            />
          )}
          {showSchedules && (
            <NextStepCard
              icon={Clock}
              title="Keep this map fresh"
              body="Harvests can run on a schedule, so new pages land without you remembering to fetch them."
              cta="Set up a schedule"
              to="/settings/schedules"
            />
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function NextStepCard({
  icon: Icon,
  title,
  body,
  cta,
  to,
}: {
  icon: typeof ListTodo;
  title: string;
  body: string;
  cta: string;
  to: string;
}) {
  const navigate = useNavigate();
  return (
    <div className="rounded-xl border border-hair bg-cream/60 p-4 flex flex-col">
      <div className="flex items-center gap-2 mb-1.5">
        <Icon size={15} strokeWidth={1.75} className="text-magenta shrink-0" aria-hidden />
        <span className="font-sans text-sm font-medium text-ink">{title}</span>
      </div>
      <p className="font-sans text-[13px] leading-relaxed text-muted flex-1">{body}</p>
      <div className="mt-3">
        <Button variant="secondary" onClick={() => navigate(to)}>
          {cta}
          <ArrowRight size={14} strokeWidth={1.75} aria-hidden />
        </Button>
      </div>
    </div>
  );
}

function LastRunNotice({
  run,
  resumeReason,
  onResume,
  pending,
}: {
  run: TerrainRun | undefined;
  resumeReason: "server restarted" | "cancelled" | "usage limit" | null;
  onResume: () => void;
  pending: boolean;
}) {
  if (!run || run.status !== "failed") return null;
  const isQuota = resumeReason === "usage limit";
  const resumable = resumeReason !== null;
  return (
    <Card className={cn("border", isQuota ? "border-amber-300/70 bg-amber-50/40" : "border-rose/40 bg-rose/5")}>
      <CardContent className="p-5 flex flex-col md:flex-row md:items-center gap-4">
        <div className="min-w-0 flex-1">
          <p className="font-serif text-lg text-ink mb-1">
            {isQuota
              ? "The last compile stopped at your AI usage limit."
              : resumable
                ? `The last compile was interrupted (${resumeReason}).`
                : "The last compile failed."}
          </p>
          <p className="font-sans text-sm text-muted max-w-prose">
            {resumable
              ? "Everything analyzed so far is saved. Resume when you're ready and only the remaining documents are processed — no work is repeated."
              : "Fix the cause below, then recompile. If the AI engine keeps failing, switch engines in Settings → AI & Models."}
          </p>
          {run.error && (
            <p className="mt-2 font-mono text-[11px] text-muted break-words">{run.error}</p>
          )}
        </div>
        {resumable && (
          <Button variant="primary" onClick={onResume} disabled={pending} className="shrink-0">
            <RefreshCw size={14} strokeWidth={1.5} />
            Resume compile
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function StatTile({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <Card className="bg-cream">
      <CardContent className="p-5 pt-5">
        <p className="eyebrow mb-2">{label}</p>
        <p className="font-serif text-4xl text-ink tabular-nums leading-none">{value.toLocaleString()}</p>
        {sub && <p className="font-sans text-xs text-muted mt-2">{sub}</p>}
      </CardContent>
    </Card>
  );
}

function HlColumn({
  title,
  desc,
  ids,
  labels,
  onPick,
}: {
  title: string;
  desc: string;
  ids: string[];
  labels?: Record<string, string>;
  onPick: (id: string) => void;
}) {
  const MAX = 20;
  return (
    <Card>
      <CardContent className="p-5">
        <header className="flex items-baseline gap-2 mb-1">
          <h3 className="font-serif text-lg text-ink">{title}</h3>
          <span className="ml-auto font-sans text-xs text-muted tabular-nums">{ids.length}</span>
        </header>
        <p className="font-sans text-xs text-muted mb-3">{desc}</p>
        {ids.length === 0 ? (
          <p className="font-sans text-xs text-muted italic">none</p>
        ) : (
          <ul className="space-y-1">
            {ids.slice(0, MAX).map((id) => (
              <li key={id}>
                <button
                  type="button"
                  onClick={() => onPick(id)}
                  className="w-full text-left px-2.5 py-1.5 rounded-lg font-serif text-sm text-ink truncate transition-colors hover:bg-lavender/30"
                >
                  {labels?.[id] ?? tagLabel(id)}
                </button>
              </li>
            ))}
            {ids.length > MAX && (
              <li className="px-2.5 pt-1 font-sans text-[11px] text-muted">+{ids.length - MAX} more</li>
            )}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function CompileRunHistory({ runs }: { runs: TerrainRun[] }) {
  return (
    <section>
      <h2 className="font-serif text-2xl text-ink mb-4">Compile history</h2>
      <ul className="space-y-2">
        {runs.map((run) => {
          const ok = run.status === "completed";
          const failed = run.status === "failed";
          let dur: string | null = null;
          if (run.started_at && run.completed_at) {
            try {
              dur = formatDuration(
                Math.max(0, (new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()) / 1000),
              );
            } catch {
              dur = null;
            }
          }
          return (
            <li
              key={run.id}
              className="flex items-center justify-between gap-4 px-4 py-3 rounded-lg bg-bone/40 border border-hair"
            >
              <div className="flex items-center gap-3 min-w-0">
                <Badge tone={ok ? "sage" : failed ? "rose" : "muted"}>
                  {ok ? "Completed" : failed ? "Failed" : run.status}
                </Badge>
                <span className="font-sans text-sm text-ink truncate">
                  {run.started_at ? relativeTime(run.started_at) : run.id}
                </span>
                {failed && run.error && (
                  <span className="font-mono text-[11px] text-rose truncate">{run.error}</span>
                )}
              </div>
              {dur && <span className="font-sans text-xs text-muted tabular-nums shrink-0">{dur}</span>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * Live log for the compile stream. Inherits the harvest LiveLogTail UX —
 * scroll-pause + jump-to-latest pill — without virtualization, since the
 * compile log is bounded (the SSE hook caps it at ~200 entries).
 *
 * Compile logs append newest-last (oldest on top), so the "latest" affordance
 * scrolls *down* rather than up. That's the only meaningful difference from
 * LiveLogTail.
 */
function CompileLogTail({ logs }: { logs: CompileLogEntry[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);

  // Auto-scroll to bottom on new entries, unless the user scrolled away.
  useEffect(() => {
    if (!atBottom) return;
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs.length, atBottom]);

  function handleScroll() {
    const el = ref.current;
    if (!el) return;
    setAtBottom(el.scrollTop + el.clientHeight >= el.scrollHeight - 8);
  }

  function jumpToLatest() {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
    setAtBottom(true);
  }

  const paused = !atBottom;

  if (logs.length === 0) {
    return (
      <div className="bg-bone/40 border border-hair rounded-2xl h-[340px] flex items-center justify-center">
        <p className="font-sans text-sm text-muted">Getting things ready…</p>
      </div>
    );
  }

  return (
    <div className="relative">
      <div
        ref={ref}
        onScroll={handleScroll}
        aria-live="polite"
        aria-atomic="false"
        aria-relevant="additions"
        aria-label="Compile log"
        className="bg-bone/40 border border-hair rounded-2xl h-[340px] overflow-y-auto p-4 font-sans text-xs leading-7"
      >
        {logs.map((l) => {
          const discovery =
            l.msg.startsWith("Found region:") || l.msg.startsWith("Tagged:");
          return (
            <div
              key={l.key}
              className={cn(
                l.level === "error"
                  ? "text-rose"
                  : discovery
                    ? "text-sage"
                    : "text-muted",
              )}
            >
              {discovery && <span aria-hidden>✦ </span>}
              {l.msg}
            </div>
          );
        })}
      </div>

      {/* Top + bottom scroll-shadows mirror LiveLogTail. */}
      {paused && (
        <div
          aria-hidden
          className="pointer-events-none absolute bottom-0 left-0 right-0 h-8 rounded-b-2xl"
          style={{
            background:
              "linear-gradient(to top, rgb(var(--c-bg) / 0.85), rgb(var(--c-bg) / 0))",
          }}
        />
      )}

      {paused && (
        <button
          type="button"
          onClick={jumpToLatest}
          className={cn(
            "absolute bottom-3 left-1/2 -translate-x-1/2 z-10",
            "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full",
            "bg-cream border border-hair shadow-sm",
            "font-sans text-[11px] text-ink hover:bg-bone",
            "animate-fade-in",
          )}
        >
          <ArrowDown size={11} strokeWidth={1.5} aria-hidden />
          Auto-scroll paused · Jump to latest
        </button>
      )}
    </div>
  );
}
