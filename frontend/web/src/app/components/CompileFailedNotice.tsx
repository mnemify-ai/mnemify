import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { AlertTriangle, ArrowRight, X } from "lucide-react";
import { useTerrainCurrent } from "../api/terrain";
import { compileFailureKey, shouldShowCompileFailure } from "../lib/compileFailure";
import { cn } from "../lib/cn";

/**
 * Floating "Compile failed" card — top-right, just under the TopBar pill that
 * narrated the compile while it ran. Shell-level, so the failure is visible
 * from any route instead of only on Build → Compile (see `compileFailure.ts`
 * for the show/hide rules).
 *
 * The polled compile snapshot is shared with `OpsPill` through the query
 * cache, so this adds no request of its own. Dismissal is per failed run and
 * lives in component state: the shell is mounted once for the whole session,
 * so it survives navigation and resets on reload — a fresh look at a still-
 * failed compile is the right default.
 */
export function CompileFailedNotice() {
  const { data } = useTerrainCurrent();
  const { pathname } = useLocation();
  const [dismissedKey, setDismissedKey] = useState<string | null>(null);

  if (!shouldShowCompileFailure(data, dismissedKey, pathname)) return null;
  const key = compileFailureKey(data!);

  return (
    <aside
      role="alert"
      aria-label="Compile failed"
      className={cn(
        // Below the TopBar (h-16, z-40); above page content, level with the
        // Ask bubble. Right edge matches the TopBar's inner gutter.
        "fixed top-20 right-6 lg:right-10 z-30 w-[22rem] max-w-[calc(100vw-3rem)]",
        "rounded-xl border border-rose/30 bg-cream shadow-lg",
        "font-sans text-sm text-ink",
      )}
    >
      <div className="flex items-start gap-3 p-4">
        <AlertTriangle
          size={16}
          strokeWidth={1.75}
          className="mt-0.5 shrink-0 text-rose"
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <p className="font-serif text-base leading-tight">Compile failed</p>
          {data!.error && (
            <p
              className="mt-1.5 font-mono text-[11px] leading-relaxed text-muted break-words line-clamp-4"
              title={data!.error}
            >
              {data!.error}
            </p>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <Link
              to="/build/compile"
              className="inline-flex items-center gap-1 text-ink hover:underline"
            >
              See details
              <ArrowRight size={12} strokeWidth={1.75} aria-hidden />
            </Link>
            <Link to="/settings/ai" className="text-muted hover:text-ink hover:underline">
              AI engine settings
            </Link>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setDismissedKey(key)}
          aria-label="Dismiss"
          className="-m-1 grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-bone hover:text-ink"
        >
          <X size={14} strokeWidth={1.75} aria-hidden />
        </button>
      </div>
    </aside>
  );
}
