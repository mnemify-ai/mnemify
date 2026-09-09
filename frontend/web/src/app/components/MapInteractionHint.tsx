import { useEffect, useState } from "react";
import { MousePointerClick, X } from "lucide-react";
import { hasClickedTag, markTagClicked } from "../lib/onboardingFlags";

/**
 * A single, focused "how to drive the map" nudge shown on Home once a map is
 * compiled — the 3D canvas gives no affordance that hexes are clickable or that
 * you can orbit/zoom, and no other surface explains it. Shows until the user
 * either selects a tag (they've got it) or dismisses it. State lives in
 * localStorage so it never nags on return visits.
 *
 * Replaces the old multi-step OnboardingChecklist: post-compile, connect →
 * harvest → compile are already done, so re-listing them as pre-checked rows
 * was noise. Setup guidance now lives solely in <MapEmptyState> (pre-compile);
 * this is purely the first-interaction hint.
 */

const HINT_DISMISSED_KEY = "mnemify.mapHintDismissed";

function readDismissed(): boolean {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem(HINT_DISMISSED_KEY) === "1";
  } catch {
    return true;
  }
}

function markDismissed(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(HINT_DISMISSED_KEY, "1");
  } catch {
    /* quota exceeded or storage disabled — silently noop */
  }
}

export function MapInteractionHint({ selectedTagId }: { selectedTagId: string | null }) {
  // Hidden if they've ever clicked a spire or previously dismissed the hint.
  const [hidden, setHidden] = useState(() => hasClickedTag() || readDismissed());

  // First-ever tag selection retires the hint for good (and records the shared
  // flag the briefing card reads to know the user is past first-interaction).
  useEffect(() => {
    if (!selectedTagId) return;
    markTagClicked();
    setHidden(true);
  }, [selectedTagId]);

  if (hidden) return null;

  return (
    <section
      role="note"
      aria-label="Map controls"
      className="glass-panel rounded-full pl-4 pr-2 py-1.5 shadow-sm flex items-center gap-2 animate-fade-in motion-reduce:animate-none"
    >
      <MousePointerClick size={14} strokeWidth={1.75} className="text-magenta shrink-0" aria-hidden />
      <span className="font-sans text-xs text-muted whitespace-nowrap">
        <span className="text-ink font-medium">Click a spire</span> to open a topic
        <span className="mx-1.5 opacity-50">·</span>
        <span className="text-ink font-medium">drag</span> to orbit
        <span className="mx-1.5 opacity-50">·</span>
        <span className="text-ink font-medium">right-drag</span> to move
        <span className="mx-1.5 opacity-50">·</span>
        <span className="text-ink font-medium">scroll</span> to zoom
      </span>
      <button
        type="button"
        onClick={() => {
          markDismissed();
          setHidden(true);
        }}
        aria-label="Dismiss map controls hint"
        className="grid place-items-center w-6 h-6 rounded-full text-muted hover:text-ink hover:bg-lavender/60 transition-colors shrink-0"
      >
        <X size={13} strokeWidth={1.75} aria-hidden />
      </button>
    </section>
  );
}
