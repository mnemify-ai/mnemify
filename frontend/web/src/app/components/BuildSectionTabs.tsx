import { NavLink } from "react-router-dom";
import { ChevronRight, History } from "lucide-react";
import { cn } from "../lib/cn";
import { useHarvestCurrent } from "../api/harvest";
import { useTerrainCurrent } from "../api/terrain";

/**
 * The pipeline, in the order a user actually walks it. History is
 * deliberately NOT a step — it's a log of past harvests — so it lives apart
 * from the chain (see below) instead of interrupting it.
 */
const STEPS = [
  { to: "/build/sources", label: "Sources", end: false },
  { to: "/build/harvest", label: "Harvest", end: true },
  { to: "/build/compile", label: "Compile", end: false },
] as const;

const HISTORY = { to: "/build/history", label: "History" };

const linkBase = cn(
  "h-8 inline-flex items-center gap-2 rounded-full",
  "font-sans text-xs font-medium whitespace-nowrap",
  "transition-colors duration-base ease-out",
  "focus:outline-none focus-visible:!shadow-none",
);

/** Small pulsing dot: "this stage is running right now". */
function RunningDot({ active }: { active: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "relative inline-flex h-1.5 w-1.5 shrink-0 rounded-full",
        active ? "bg-cream" : "bg-magenta",
      )}
    >
      <span
        className={cn(
          "absolute inset-0 rounded-full animate-ping",
          active ? "bg-cream/70" : "bg-magenta/60",
        )}
      />
    </span>
  );
}

/**
 * Inline pipeline stepper that swaps between the /build sub-sections.
 * Reads as a chain — ① Sources › ② Harvest › ③ Compile — so the "what comes
 * next" question answers itself, and the stage currently running shows a
 * live dot. History sits behind a hairline at the end, styled as a quiet
 * secondary link rather than a fourth step.
 *
 * Each Build page renders this near the top, alongside its title, so there's
 * only ever one nav bar visible (the main TopBar). The status hooks reuse
 * the polls TopBar/OpsPill already run — no extra requests.
 */
export function BuildSectionTabs({ className }: { className?: string }) {
  const harvest = useHarvestCurrent();
  const compile = useTerrainCurrent();
  const running: Record<string, boolean> = {
    "/build/harvest": harvest.data?.status === "running",
    "/build/compile": compile.data?.status === "running",
  };

  return (
    <nav
      aria-label="Build sections"
      className={cn(
        "inline-flex items-center gap-0.5 rounded-full bg-bone/70 border border-hair p-1",
        className,
      )}
    >
      <ol className="contents">
        {STEPS.map((step, i) => (
          <li key={step.to} className="contents">
            {i > 0 && (
              <ChevronRight
                size={12}
                strokeWidth={2}
                aria-hidden
                className="shrink-0 text-muted/50 -mx-0.5"
              />
            )}
            <NavLink
              to={step.to}
              end={step.end}
              className={({ isActive }) =>
                cn(
                  linkBase,
                  "pl-1.5 pr-3.5",
                  isActive ? "bg-ink text-cream" : "text-muted hover:text-ink",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span
                    aria-hidden
                    className={cn(
                      "grid h-5 w-5 place-items-center rounded-full",
                      "font-mono text-[10px] leading-none tabular-nums",
                      isActive ? "bg-cream/15 text-cream" : "bg-ink/[0.06] text-muted",
                    )}
                  >
                    {i + 1}
                  </span>
                  <span className="sr-only">Step {i + 1}: </span>
                  {step.label}
                  {running[step.to] && <RunningDot active={isActive} />}
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ol>

      <span aria-hidden className="mx-1.5 h-4 w-px bg-hair" />

      <NavLink
        to={HISTORY.to}
        className={({ isActive }) =>
          cn(
            linkBase,
            "px-3",
            isActive ? "bg-ink text-cream" : "text-muted hover:text-ink",
          )
        }
      >
        <History size={13} strokeWidth={1.75} aria-hidden />
        {HISTORY.label}
      </NavLink>
    </nav>
  );
}
