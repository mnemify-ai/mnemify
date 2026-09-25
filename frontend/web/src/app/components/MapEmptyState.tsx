import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowRight, Check } from "lucide-react";
import { cn } from "../lib/cn";
import { Button } from "./ui/Button";
import { Dialog } from "./ui/Dialog";
import { SourceBadge } from "./SourceBadge";
import { AiModePicker, useCompileOverrides } from "./AiModePicker";
import { NotionWizard } from "./wizards/NotionWizard";
import { ConfluenceWizard } from "./wizards/ConfluenceWizard";
import { ObsidianWizard } from "./wizards/ObsidianWizard";
import { LocalFilesWizard } from "./wizards/LocalFilesWizard";
import { useHarvestCurrent, useStartHarvest } from "../api/harvest";
import { useStartCompile, useTerrainCurrent } from "../api/terrain";
import { qk } from "../api/keys";

type ConnectSource = "notion" | "confluence" | "obsidian" | "localfiles";

interface StepConfig {
  n: number;
  done: boolean;
  title: string;
  body: string;
  cta: string;
  /** Run the step in place (open a wizard/dialog or fire a mutation). */
  action: () => void;
  /** Gate steps whose prerequisites aren't met (or that are mid-run). */
  disabled?: boolean;
  /** Optional compact "what you'll get" hint rendered under the CTA. */
  hint?: ReactNode;
}

export interface MapEmptyStateProps {
  /** Has at least one source been connected? */
  connected: boolean;
  /** Have any documents been harvested? */
  harvested: boolean;
  /** Has a compile run produced terrain? (true even if the v3 render bake failed) */
  compiled: boolean;
  /** Compile succeeded but render-data.json didn't land — needs a recompile. */
  renderFailed?: boolean;
  /** Open the bundled sample terrain (secondary "Explore a sample map" link). */
  onTryDemo?: () => void;
}

/**
 * Full-bleed "no map yet" screen — shown on the home page (and the
 * other no-terrain surfaces) instead of the 3D map. A dormant hex-field
 * silhouette + a soft pulsing seed, with the connect → harvest → compile path
 * overlaid. Animations are auto-disabled under prefers-reduced-motion (see
 * theme/index.css) — we also tag them `motion-reduce:animate-none`.
 */
export function MapEmptyState({
  connected,
  harvested,
  compiled,
  renderFailed,
  onTryDemo,
}: MapEmptyStateProps) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const startHarvest = useStartHarvest();
  const startCompile = useStartCompile();

  // Live run state — drives inline progress labels + step gating. Both pills in
  // the TopBar already poll these query keys, so reading them here adds no
  // extra requests.
  const harvest = useHarvestCurrent({ poll: true });
  const compileCur = useTerrainCurrent({ poll: true });
  const harvestRunning = harvest.data?.status === "running";
  const compileRunning = compileCur.data?.status === "running";

  // When a harvest finishes, refresh the doc/connection stats so step 2 flips
  // to done (and step 3 unlocks) without waiting for staleTime/refocus.
  const prevHarvestStatus = useRef(harvest.data?.status);
  useEffect(() => {
    const before = prevHarvestStatus.current;
    prevHarvestStatus.current = harvest.data?.status;
    if (before === "running" && harvest.data?.status && harvest.data.status !== "running") {
      qc.invalidateQueries({ queryKey: qk.documentStats() });
      qc.invalidateQueries({ queryKey: qk.connections() });
    }
  }, [harvest.data?.status, qc]);

  // In-place flow state: which connect wizard is open, and the compile dialog.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [connectSource, setConnectSource] = useState<ConnectSource | null>(null);
  const [compileOpen, setCompileOpen] = useState(false);
  const overrides = useCompileOverrides();

  const runHarvest = () => {
    startHarvest.mutate(
      { sources: null },
      {
        onSuccess: () =>
          toast.success("Harvesting your sources…", { description: "Track progress in the top bar." }),
        onError: (e) => toast.error("Couldn't start harvest", { description: String(e) }),
      },
    );
  };

  const runCompile = () => {
    startCompile.mutate(
      overrides.payload,
      {
        onSuccess: (res) => {
          setCompileOpen(false);
          if (res.dismissed) return; // closed the local-embeddings dialog
          if (!res.ok) {
            toast.error("Couldn't start compile", {
              description: res.reason ?? "Open the Compile page for options.",
            });
            return;
          }
          const engine =
            res.ai_mode === "local"
              ? "local heuristics"
              : res.ai_mode === "claude"
                ? "Claude (subscription)"
                : "OpenAI";
          toast.success(`Compiling with ${engine}…`, { description: "Your map appears here when it's done." });
        },
        onError: (e) => toast.error("Couldn't start compile", { description: String(e) }),
      },
    );
  };

  // Cold start = nothing connected yet (and nothing to repair). One job on
  // screen: connect a source. The step path and the sample map are held back
  // (steps would show three chores before the user has begun; the sample
  // becomes a quiet secondary link). Once anything is connected the
  // step-progress view takes over.
  const coldStart = !connected && !harvested && !compiled && !renderFailed;

  const steps: StepConfig[] = [
    {
      n: 1,
      done: connected,
      title: "Connect a source",
      body: "Pick Notion, Obsidian, or Confluence and grant Mnemify access. Tokens stay on this machine.",
      cta: connected ? "Manage sources" : "Connect a source",
      action: connected ? () => navigate("/build/sources") : () => setPickerOpen(true),
      // Sample-outcome hint right under the connect action: what you get, and
      // roughly how long it takes. Only until something is connected.
      hint: connected ? undefined : <ConnectOutcomeHint />,
    },
    {
      n: 2,
      done: harvested,
      title: "Harvest documents",
      body: "Pull your notes and pages onto disk. Mnemify deduplicates by content hash and only fetches what changed.",
      cta: harvestRunning ? "Harvesting…" : harvested ? "Re-harvest" : "Run a harvest",
      action: runHarvest,
      disabled: !connected || harvestRunning || startHarvest.isPending,
    },
    {
      n: 3,
      done: compiled,
      title: "Compile the map",
      body: "Cluster, name, and lay out your documents into a 3D map you can explore.",
      cta: compileRunning ? "Compiling…" : compiled ? "Recompile" : "Compile",
      action: () => setCompileOpen(true),
      disabled: !harvested || compileRunning || startCompile.isPending,
    },
  ];
  // Primary-action heuristic: the first incomplete step is the user's current
  // step — its button gets `primary`; completed steps show as `secondary`
  // ghosts; later steps stay `secondary` but disabled until prerequisites are
  // met. As the live queries flip each step done, the highlight advances on its
  // own (#3) — no manual stepping.
  const firstIncomplete = steps.find((s) => !s.done) ?? steps[steps.length - 1];

  return (
    <div className="absolute inset-0 overflow-hidden bg-cream">
      {/* dormant hex-field wallpaper — purely decorative */}
      <svg className="absolute inset-0 h-full w-full" aria-hidden="true">
        <defs>
          <pattern id="hexbg" width="56" height="48.5" patternUnits="userSpaceOnUse" patternTransform="translate(0 0)">
            {/* a pointy-top hexagon outline */}
            <path
              d="M14 0 L42 0 L56 24.25 L42 48.5 L14 48.5 L0 24.25 Z"
              fill="none"
              stroke="rgb(var(--c-line))"
              strokeOpacity="0.05"
              strokeWidth="1"
            />
          </pattern>
          <radialGradient id="glow" cx="50%" cy="46%" r="42%">
            <stop offset="0%" stopColor="rgb(var(--c-magenta))" stopOpacity="0.14" />
            <stop offset="55%" stopColor="rgb(var(--c-magenta))" stopOpacity="0.04" />
            <stop offset="100%" stopColor="rgb(var(--c-magenta))" stopOpacity="0" />
          </radialGradient>
        </defs>
        <rect width="100%" height="100%" fill="url(#hexbg)" />
        <rect width="100%" height="100%" fill="url(#glow)" />
      </svg>

      {/* hero (post-connect layout only): documents trickling into a hex
          terrain, floating above the wide three-step panel pinned at the
          bottom. The cold-start hero is laid out in flow below instead. */}
      {!coldStart && (
        <DocsToTerrain className="absolute left-1/2 top-[42%] -translate-x-1/2 -translate-y-1/2" />
      )}

      {/* The path forward. Inset by the TopBar's height: the bar is
          `fixed h-16`, so it's out of flow and would otherwise paint over the
          top of this layer — which is what clipped the hero's document glyphs.
          The wallpaper above stays full-bleed so the translucent bar still has
          hexes behind it. */}
      <div className="absolute inset-x-0 top-16 bottom-0 overflow-y-auto px-6">
        <div
          className={cn(
            "min-h-full flex flex-col items-center",
            // Cold start stacks hero over panel as one centered group, so the
            // two can't collide at any viewport height (they did when both
            // were absolutely positioned against percentages).
            coldStart ? "justify-center gap-8 py-8" : "justify-end pb-[8vh]",
          )}
        >
          {coldStart && <DocsToTerrain compact className="shrink-0" />}
          <div
            className={cn(
              "glass-panel rounded-2xl shadow-sm w-full",
              coldStart ? "max-w-[640px] px-8 py-8" : "max-w-4xl px-8 py-7",
            )}
          >
            <p className="eyebrow mb-1">Your Knowledge Map</p>
            <h1 className="font-serif text-3xl text-ink leading-tight mb-1.5">
              {renderFailed
                ? "Compiled — but the map didn't render"
                : coldStart
                  ? "Bring your knowledge together."
                  : "Ready when you are"}
            </h1>
            <p className="font-sans text-sm text-muted mb-6 max-w-prose">
              {renderFailed
                ? "The last compile produced the data but the 3D layout step failed. Recompile to try again."
                : coldStart
                  ? "Connect your notes and documents to build a map you can explore and ask questions about."
                  : "Three steps from here to your first Knowledge Map. Each step has its own surface — start with what's next."}
            </p>
            {renderFailed ? (
              <Button
                type="button"
                variant="primary"
                onClick={() => setCompileOpen(true)}
              >
                Recompile
                <ArrowRight size={14} strokeWidth={1.75} aria-hidden="true" />
              </Button>
            ) : coldStart ? (
              <>
                <Button type="button" variant="primary" onClick={() => setPickerOpen(true)}>
                  Connect a source
                  <ArrowRight size={14} strokeWidth={1.75} aria-hidden="true" />
                </Button>
                {/* Supported sources — each chip jumps straight into its wizard. */}
                <ul className="mt-4 flex flex-wrap items-center gap-2" aria-label="Supported sources">
                  {(["notion", "obsidian", "confluence", "localfiles"] as const).map((src) => (
                    <li key={src}>
                      <button
                        type="button"
                        onClick={() => setConnectSource(src)}
                        className="inline-flex items-center rounded-full border border-hair bg-bone/40 hover:bg-bone px-3 py-1.5 transition-colors"
                      >
                        <SourceBadge source={src} size="sm" />
                      </button>
                    </li>
                  ))}
                </ul>
                {onTryDemo && (
                  <p className="mt-6 font-sans text-xs text-muted">
                    <button
                      type="button"
                      onClick={onTryDemo}
                      className="text-magenta hover:underline underline-offset-2"
                    >
                      Explore a sample map →
                    </button>
                  </p>
                )}
              </>
            ) : (
              <>
                <ol className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-5">
                  {steps.map((s) => (
                    <StepCard
                      key={s.n}
                      step={s}
                      isCurrent={s === firstIncomplete}
                      onGo={s.action}
                    />
                  ))}
                </ol>
                {onTryDemo && (
                  <p className="mt-5 font-sans text-xs text-muted">
                    Not ready to connect?{" "}
                    <button
                      type="button"
                      onClick={onTryDemo}
                      className="text-magenta hover:underline underline-offset-2"
                    >
                      Explore a sample map first →
                    </button>
                  </p>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* ── In-place flow: source picker → wizard, and the compile dialog ── */}
      <Dialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        ariaLabel="Choose a source to connect"
        width="440px"
      >
        <div className="p-6">
          <p className="eyebrow mb-1">Connect</p>
          <h2 className="font-serif text-2xl text-ink mb-1">Choose a source</h2>
          <p className="font-sans text-sm text-muted mb-5">
            Mnemify reads from these. Tokens stay on this machine.
          </p>
          <div className="grid gap-2">
            {(["notion", "confluence", "obsidian", "localfiles"] as const).map((src) => (
              <button
                key={src}
                type="button"
                onClick={() => {
                  setPickerOpen(false);
                  setConnectSource(src);
                }}
                className="flex items-center gap-3 px-4 py-3 rounded-xl border border-hair bg-bone/40 hover:bg-bone text-left transition-colors"
              >
                <SourceBadge source={src} />
                <ArrowRight size={15} strokeWidth={1.75} className="ml-auto text-muted" aria-hidden />
              </button>
            ))}
          </div>
        </div>
      </Dialog>

      <NotionWizard open={connectSource === "notion"} onClose={() => setConnectSource(null)} />
      <ConfluenceWizard open={connectSource === "confluence"} onClose={() => setConnectSource(null)} />
      <ObsidianWizard open={connectSource === "obsidian"} onClose={() => setConnectSource(null)} />
      <LocalFilesWizard open={connectSource === "localfiles"} onClose={() => setConnectSource(null)} />

      <Dialog
        open={compileOpen}
        onOpenChange={setCompileOpen}
        ariaLabel="Compile your map"
        width="560px"
      >
        <div className="p-6">
          <p className="eyebrow mb-1">Compile</p>
          <h2 className="font-serif text-2xl text-ink mb-1">Build your Knowledge Map</h2>
          <p className="font-sans text-sm text-muted mb-5">
            Cluster, name, and lay out your documents into a 3D map. Choose how naming &amp;
            clustering run:
          </p>
          <AiModePicker overrides={overrides} />
          <div className="mt-6 flex justify-end gap-3">
            <Button type="button" variant="secondary" onClick={() => setCompileOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={runCompile}
              loading={startCompile.isPending}
            >
              Compile
              <ArrowRight size={14} strokeWidth={1.75} aria-hidden="true" />
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}

/**
 * One column in the horizontal stepper. Number/check badge + title + body +
 * action button. The current step (first incomplete) gets `primary`; completed
 * steps get `secondary` with a sage check; later steps get `secondary` and are
 * disabled until their prerequisite step is done (so you can't fire a harvest
 * with nothing connected, or a compile with nothing harvested).
 */
function StepCard({
  step,
  isCurrent,
  onGo,
}: {
  step: StepConfig;
  isCurrent: boolean;
  onGo: () => void;
}) {
  return (
    <li
      className={cn(
        "rounded-xl p-4 border transition-colors",
        isCurrent
          ? "bg-cream border-magenta/30"
          : step.done
            ? "bg-bone/30 border-hair"
            : "bg-bone/20 border-hair",
      )}
    >
      <header className="flex items-center gap-2.5 mb-2">
        <span
          className={cn(
            "h-6 w-6 rounded-full flex items-center justify-center shrink-0 font-sans text-[11px] font-medium",
            step.done
              ? "bg-sage text-cream"
              : isCurrent
                ? "bg-magenta text-cream"
                : "bg-bone text-muted border border-hair",
          )}
          aria-hidden="true"
        >
          {step.done ? <Check size={12} strokeWidth={3} /> : step.n}
        </span>
        <h3
          className={cn(
            "font-serif text-base leading-tight",
            step.done ? "text-muted" : "text-ink",
          )}
        >
          {step.title}
        </h3>
      </header>
      <p className="font-sans text-xs text-muted leading-relaxed mb-4 min-h-[3em]">
        {step.body}
      </p>
      <Button
        type="button"
        variant={isCurrent ? "primary" : "secondary"}
        size="sm"
        onClick={onGo}
        disabled={step.disabled}
        className="w-full"
      >
        {step.cta}
        {isCurrent && !step.disabled && (
          <ArrowRight size={13} strokeWidth={1.75} aria-hidden="true" />
        )}
      </Button>
      {step.hint}
    </li>
  );
}

/**
 * Compact sample-outcome hint under the connect CTA: a miniature dormant hex
 * field (same visual language as the wallpaper + spire) beside one honest
 * line about what a connected source turns into.
 */
function ConnectOutcomeHint() {
  // Flat-top mini hex with circumradius `r` centered at (cx, cy) — same
  // geometry as HexTerrain, shrunk.
  const r = 6;
  const hex = (cx: number, cy: number) =>
    `M ${cx - r} ${cy}
     L ${cx - r / 2} ${cy - r * 0.866}
     L ${cx + r / 2} ${cy - r * 0.866}
     L ${cx + r} ${cy}
     L ${cx + r / 2} ${cy + r * 0.866}
     L ${cx - r / 2} ${cy + r * 0.866} Z`;
  return (
    <div className="mt-3 flex items-start gap-2.5">
      <svg viewBox="0 0 46 22" className="w-[46px] h-auto shrink-0 mt-0.5" aria-hidden="true">
        {/* two dormant neighbours + a raised magenta center, echoing the spire */}
        <path
          d={hex(9, 14)}
          fill="rgb(var(--c-bone))"
          stroke="rgb(var(--c-line))"
          strokeOpacity="0.3"
          strokeWidth="1"
        />
        <path
          d={hex(37, 14)}
          fill="rgb(var(--c-bone))"
          stroke="rgb(var(--c-line))"
          strokeOpacity="0.3"
          strokeWidth="1"
        />
        <path
          d={hex(23, 9)}
          fill="rgb(var(--c-magenta))"
          fillOpacity="0.8"
        />
      </svg>
      <p className="font-sans text-[11px] text-muted leading-relaxed">
        A few hundred pages become a map of regions, topics, and every open
        question — usually in about ten minutes.
      </p>
    </div>
  );
}

/**
 * Hero graphic for the empty state. Three paper-icon glyphs drift gently
 * at the top of the viewport, with soft magenta trails leading down to a
 * hex terrain at the bottom. The center spire — where the trails converge —
 * pulses softly: this is the "documents become map" metaphor.
 *
 * Pure SVG. Animations are CSS keyframes scoped via a `<style>` block;
 * `prefers-reduced-motion` is honored by the global `*::transition-duration`
 * override in theme/index.css plus an explicit `animation: none` rule below.
 */
function DocsToTerrain({ compact, className }: { compact?: boolean; className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        // Positioning is the caller's business — cold start lays this out in
        // flow above the panel, the post-connect layout floats it absolutely.
        "pointer-events-none",
        compact ? "w-[min(360px,80vw)]" : "w-[min(520px,90vw)]",
        className,
      )}
    >
      <svg
        viewBox="0 0 420 260"
        className="w-full h-auto drop-shadow-sm"
        role="img"
      >
        <style>{`
          @keyframes doc-bob-a {
            0%, 100% { transform: translate3d(0, 0, 0); }
            50%      { transform: translate3d(0, -4px, 0); }
          }
          @keyframes doc-bob-b {
            0%, 100% { transform: translate3d(0, -2px, 0); }
            50%      { transform: translate3d(0, 4px, 0); }
          }
          @keyframes trail-flow {
            0%   { stroke-dashoffset: 24; opacity: 0.0; }
            40%  { opacity: 0.55; }
            100% { stroke-dashoffset: 0;  opacity: 0.0; }
          }
          @keyframes spire-pulse {
            0%, 100% { opacity: 0.85; }
            50%      { opacity: 1.0; }
          }
          .docs-to-terrain .doc-a { animation: doc-bob-a 4.2s ease-in-out infinite; transform-origin: center; }
          .docs-to-terrain .doc-b { animation: doc-bob-b 3.6s ease-in-out infinite; animation-delay: .4s; transform-origin: center; }
          .docs-to-terrain .doc-c { animation: doc-bob-a 4.8s ease-in-out infinite; animation-delay: .9s; transform-origin: center; }
          .docs-to-terrain .trail {
            stroke-dasharray: 4 6;
            animation: trail-flow 3.2s linear infinite;
          }
          .docs-to-terrain .trail-b { animation-delay: 1.1s; }
          .docs-to-terrain .trail-c { animation-delay: 2.0s; }
          .docs-to-terrain .spire   { animation: spire-pulse 3s ease-in-out infinite; transform-origin: center; }
          @media (prefers-reduced-motion: reduce) {
            .docs-to-terrain .doc-a,
            .docs-to-terrain .doc-b,
            .docs-to-terrain .doc-c,
            .docs-to-terrain .trail,
            .docs-to-terrain .spire { animation: none !important; }
          }
        `}</style>

        <g className="docs-to-terrain">
          {/* — three paper-icon glyphs at the top.
              Y values are pushed well inside the viewBox top edge so the
              full page rect (rect spans ±32 around the y center) never
              clips. — */}
          <DocGlyph x={75} y={56} rotate={-6} bobClass="doc-a" />
          <DocGlyph x={210} y={44} rotate={3} bobClass="doc-b" />
          <DocGlyph x={345} y={58} rotate={-2} bobClass="doc-c" />

          {/* — trails: dashed magenta paths from each doc to the spire — */}
          <path
            d="M 90 96 Q 130 124, 205 152"
            className="trail"
            fill="none"
            stroke="rgb(var(--c-magenta))"
            strokeWidth="1.25"
            strokeLinecap="round"
            opacity="0.45"
          />
          <path
            d="M 210 86 Q 210 118, 210 150"
            className="trail trail-b"
            fill="none"
            stroke="rgb(var(--c-magenta))"
            strokeWidth="1.25"
            strokeLinecap="round"
            opacity="0.45"
          />
          <path
            d="M 330 98 Q 285 122, 215 152"
            className="trail trail-c"
            fill="none"
            stroke="rgb(var(--c-magenta))"
            strokeWidth="1.25"
            strokeLinecap="round"
            opacity="0.45"
          />

          {/* — hex terrain — three rows building up to a central spire — */}
          <HexTerrain />
        </g>
      </svg>
    </div>
  );
}

/**
 * A small "paper" icon: rounded rectangle with three short text-indicator
 * lines. Tilts slightly for life. Uses the bone token for fill and a
 * magenta-tinted hairline for the border so it ties to the brand.
 *
 * Note on the nested `<g>` structure: per the SVG2 spec, a CSS `transform`
 * (which our bob keyframes apply) replaces — rather than composes with —
 * any SVG `transform` attribute on the same element. That means putting
 * both on one element loses the position. So we split:
 *   outer <g>  → SVG-attribute positioning (translate)
 *   middle <g> → CSS bob animation (transform: translateY)
 *   inner <g>  → SVG-attribute rotation
 * Each transform lives in isolation; nothing is overwritten.
 */
function DocGlyph({
  x,
  y,
  rotate,
  bobClass,
}: {
  x: number;
  y: number;
  rotate: number;
  bobClass?: string;
}) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <g className={bobClass}>
        <g transform={`rotate(${rotate})`}>
          {/* page body */}
          <rect
            x={-26}
            y={-32}
            width={52}
            height={64}
            rx={4}
            fill="rgb(var(--c-bone))"
            stroke="rgb(var(--c-magenta))"
            strokeOpacity="0.4"
            strokeWidth="1.25"
          />
          {/* folded corner */}
          <path
            d="M 14 -32 L 26 -20 L 14 -20 Z"
            fill="rgb(var(--c-bg))"
            stroke="rgb(var(--c-magenta))"
            strokeOpacity="0.4"
            strokeWidth="1.25"
            strokeLinejoin="round"
          />
          {/* text lines */}
          <rect x={-18} y={-12} width={36} height={2} rx={1} fill="rgb(var(--c-muted))" opacity="0.45" />
          <rect x={-18} y={-4}  width={28} height={2} rx={1} fill="rgb(var(--c-muted))" opacity="0.45" />
          <rect x={-18} y={4}   width={32} height={2} rx={1} fill="rgb(var(--c-muted))" opacity="0.45" />
          <rect x={-18} y={12}  width={22} height={2} rx={1} fill="rgb(var(--c-muted))" opacity="0.45" />
          <rect x={-18} y={20}  width={30} height={2} rx={1} fill="rgb(var(--c-muted))" opacity="0.45" />
        </g>
      </g>
    </g>
  );
}

/**
 * Hex terrain: three rows of flat-top hexagons receding into the distance,
 * plus a tall central spire where the doc trails land. Back row is muted,
 * front row is fuller; the spire is filled magenta and animates a pulse.
 */
function HexTerrain() {
  // Flat-top hex with circumradius `r` centered at (cx, cy):
  //   horizontal step between centers in a row = 1.5 * r
  //   vertical half-step = r * sin(60°) ≈ r * 0.866
  const r = 14;
  const HEX = (cx: number, cy: number, scaleY = 1) =>
    `M ${cx - r} ${cy}
     L ${cx - r / 2} ${cy - r * 0.866 * scaleY}
     L ${cx + r / 2} ${cy - r * 0.866 * scaleY}
     L ${cx + r} ${cy}
     L ${cx + r / 2} ${cy + r * 0.866 * scaleY}
     L ${cx - r / 2} ${cy + r * 0.866 * scaleY} Z`;

  // Back row (further away, dimmer)
  const backY = 168;
  const backCenters = [30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360, 390];
  // Mid row (interleaved, slightly forward)
  const midY = 186;
  const midCenters = [45, 75, 105, 135, 165, 195, 225, 255, 285, 315, 345, 375];
  // Front row (closest; the central pair is replaced by the spire)
  const frontY = 208;
  const frontCenters = [30, 60, 90, 120, 150, 180, 240, 270, 300, 330, 360, 390];

  return (
    <g>
      {/* Back row */}
      {backCenters.map((cx) => (
        <path
          key={`b-${cx}`}
          d={HEX(cx, backY)}
          fill="rgb(var(--c-bone))"
          stroke="rgb(var(--c-line))"
          strokeOpacity="0.15"
          strokeWidth="1"
          opacity="0.55"
        />
      ))}
      {/* Mid row — a touch brighter */}
      {midCenters.map((cx) => (
        <path
          key={`m-${cx}`}
          d={HEX(cx, midY)}
          fill="rgb(var(--c-bone))"
          stroke="rgb(var(--c-line))"
          strokeOpacity="0.22"
          strokeWidth="1"
          opacity="0.8"
        />
      ))}
      {/* Front row — brightest */}
      {frontCenters.map((cx) => (
        <path
          key={`f-${cx}`}
          d={HEX(cx, frontY)}
          fill="rgb(var(--c-bone))"
          stroke="rgb(var(--c-line))"
          strokeOpacity="0.32"
          strokeWidth="1"
        />
      ))}

      {/* Central spire — a magenta-filled hex extended upward.
          The path uses elongated vertical sides to look like a prism rising
          from the front row. A glow underneath softens its edge. */}
      <ellipse
        cx={210}
        cy={216}
        rx={28}
        ry={6}
        fill="rgb(var(--c-magenta))"
        opacity="0.15"
      />
      <path
        d={`M 210 142
            L 224 154
            L 224 208
            L 210 220
            L 196 208
            L 196 154 Z`}
        fill="rgb(var(--c-magenta))"
        fillOpacity="0.85"
        className="spire"
      />
      {/* spire highlight ridge */}
      <path
        d="M 210 142 L 224 154 L 224 208"
        fill="none"
        stroke="rgb(var(--c-magenta))"
        strokeOpacity="0.55"
        strokeWidth="1"
      />
    </g>
  );
}
