import { useEffect, useMemo, useState } from "react";

/**
 * SynapseBurst — on-brand celebration when a new source connects.
 *
 * A single soft magenta ring + center dot scales out from the viewport
 * centre. No rainbow particles, no toast competition: the actual message
 * lives in the `toastSynapse` Sonner toast. This is purely a quiet visual
 * accent — the toast carries the words.
 *
 * Reduced-motion: render nothing.
 */
interface SynapseBurstProps {
  /** Fired once the animation has finished and the element can unmount. */
  onDone: () => void;
}

const TOTAL_MS = 1200;

export function SynapseBurst({ onDone }: SynapseBurstProps) {
  const prefersReduced = useMemo(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  }, []);

  const [mounted, setMounted] = useState(true);

  useEffect(() => {
    if (prefersReduced) {
      const t = window.setTimeout(onDone, 0);
      return () => window.clearTimeout(t);
    }
    const t = window.setTimeout(() => {
      setMounted(false);
      onDone();
    }, TOTAL_MS);
    return () => window.clearTimeout(t);
  }, [onDone, prefersReduced]);

  if (prefersReduced || !mounted) return null;

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 z-[60] flex items-center justify-center"
    >
      <div className="relative h-2 w-2">
        {/* Inner dot */}
        <span className="absolute inset-0 rounded-full bg-magenta/80 animate-synapse-core" />
        {/* Two expanding rings, slightly offset */}
        <span className="absolute -inset-1 rounded-full border border-magenta/60 animate-synapse-ring" />
        <span
          className="absolute -inset-1 rounded-full border border-magenta/40 animate-synapse-ring"
          style={{ animationDelay: "180ms" }}
        />
      </div>
    </div>
  );
}

/**
 * One-time gate for the first-ever synapse burst. Returns `true` exactly once
 * across the lifetime of this browser profile, and persists the flip via
 * localStorage.
 */
export function shouldShowFirstSynapseBurst(): boolean {
  if (typeof window === "undefined") return false;
  const KEY = "mnemify.firstSynapseShown";
  try {
    if (window.localStorage.getItem(KEY)) return false;
    window.localStorage.setItem(KEY, "1");
    return true;
  } catch {
    return false;
  }
}
