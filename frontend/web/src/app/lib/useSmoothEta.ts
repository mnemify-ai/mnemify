import { useEffect, useRef, useState } from "react";

/** Smooth a remaining-seconds ETA for display.
 *
 *  Backend rate samples arrive at 1–2 Hz which causes the formatted ETA to
 *  jump in steps ("1m 30s" → "1m 12s" → "1m 25s") even though the actual
 *  countdown should be steady. This hook keeps an internally-tracked
 *  ``displayed`` value that:
 *
 *    • decrements at 1 s/s between samples (so the countdown ticks visibly);
 *    • exponentially pulls toward the latest target when a new sample
 *      arrives, instead of snapping (so noisy rates don't cause flicker);
 *    • snaps when the gap is large (≥ 30 s in absolute terms, or the target
 *      changes from / to null) — a meaningful change shouldn't be hidden
 *      behind smoothing.
 *
 *  Returns ``null`` until we have a real target. The output is in seconds
 *  and is intended to be fed straight to ``formatEta``.
 */
export function useSmoothEta(targetSec: number | null | undefined): number | null {
  const target = targetSec == null || !Number.isFinite(targetSec) ? null : targetSec;
  const [display, setDisplay] = useState<number | null>(target);
  const targetRef = useRef<number | null>(target);
  const lastTickRef = useRef<number>(typeof performance !== "undefined" ? performance.now() : 0);

  // Track latest target without retriggering the timer effect.
  useEffect(() => {
    const prevTarget = targetRef.current;
    targetRef.current = target;
    setDisplay((prev) => {
      if (target === null) return null;
      if (prev === null) return target;
      // Snap when the gap is too large to smoothly catch up to within ~3s,
      // or when we just came back from a null target.
      const gap = Math.abs(target - prev);
      if (prevTarget === null || gap >= 30) return target;
      return prev;
    });
  }, [target]);

  // Animation loop — 4 Hz is plenty for a countdown that's read in seconds.
  useEffect(() => {
    const intervalMs = 250;
    const id = window.setInterval(() => {
      const now = performance.now();
      const elapsed = Math.max(0, (now - lastTickRef.current) / 1000);
      lastTickRef.current = now;
      setDisplay((prev) => {
        const t = targetRef.current;
        if (prev === null || t === null) return prev;
        // 1) Decrement at 1 s/s.
        let next = prev - elapsed;
        // 2) Pull toward target. tau = 1.5s — about 4s to converge on a
        //    small step, fast enough to feel responsive but not jumpy.
        const tau = 1.5;
        const alpha = 1 - Math.exp(-elapsed / tau);
        next += (t - next) * alpha;
        return Math.max(0, next);
      });
    }, intervalMs);
    return () => window.clearInterval(id);
  }, []);

  return display;
}
