import { isSamplePath } from "../demo/samplePaths";

/**
 * "Now" for relative-time labels. The sample workspace (app/demo) freezes it
 * at the moment its fixtures were exported, so "refreshed 2h ago" and "due in
 * 3 days" agree with the dates written inside its documents and answers no
 * matter when someone opens it.
 *
 * The freeze only applies while the URL is inside /sample. The router updates
 * the location before it renders the next route, so the first render after
 * leaving already reads real time, with no effect timing involved.
 */
let frozenAt: number | null = null;

export function nowMs(): number {
  if (frozenAt !== null && typeof window !== "undefined" && isSamplePath(window.location.pathname)) {
    return frozenAt;
  }
  return Date.now();
}

export function freezeClock(ms: number | null): void {
  frozenAt = ms;
}
