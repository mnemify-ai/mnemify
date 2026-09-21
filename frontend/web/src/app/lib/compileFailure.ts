import type { CompileCurrent } from "../api/terrain";

/**
 * Whether the shell should float the "Compile failed" card for this state.
 *
 * The card exists because a failed compile otherwise vanishes from view: the
 * TopBar pill only narrates a *running* compile, and the full failure panel
 * lives on Build → Compile, which the user may never open. So the shell shows
 * a small dismissable card on every other route until the user acts on it or
 * a new compile starts.
 *
 *  - Only for `status === "failed"`.
 *  - Never on the compile report page itself — it already shows the failure
 *    in full, and doubling it up there would be noise.
 *  - Hidden once dismissed *for that run* (keyed below); the next failure
 *    is a new run and shows again.
 *
 * Pure — unit-tested.
 */
export function shouldShowCompileFailure(
  current: Pick<CompileCurrent, "status" | "run_id" | "finished_at"> | undefined | null,
  dismissedKey: string | null,
  pathname: string,
): boolean {
  if (!current || current.status !== "failed") return false;
  if (pathname.startsWith("/build/compile")) return false;
  return compileFailureKey(current) !== dismissedKey;
}

/** Identity of one failed run, so a dismissal outlives re-renders but not the
 *  next failure. `run_id` is null when the refusal happened before a run row
 *  was written, hence the `finished_at` fallback. */
export function compileFailureKey(
  current: Pick<CompileCurrent, "run_id" | "finished_at">,
): string {
  return current.run_id ?? String(current.finished_at ?? "failed");
}
