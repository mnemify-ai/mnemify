/**
 * Behavior knobs shared across the frontend. Lift values here when:
 *   - they're used in more than one file, or
 *   - the name makes their meaning more obvious than the literal would.
 *
 * One-off animation durations and intrinsic math live at their call sites.
 */

/** Max log lines retained in the live tail (UI memory cap; backend isn't asked
 *  to forget anything). Same value used by the harvest and compile streams so
 *  both panels feel consistent. */
export const LOG_TAIL_BUFFER_LIMIT = 200;

/** EWMA weight on each fresh per-source rate sample. ~0.2 means the last ~5
 *  samples dominate; at 2–7 progress events/sec that's a couple seconds of
 *  memory — steady enough to stop the ETA jumping (the previous frontend used
 *  ~0.3) without lagging a genuine slowdown by more than a few seconds.
 *  Invariant: 0 < α < 1. */
export const RATE_EWMA_ALPHA = 0.2;

/** Initial reconnect delay after an SSE error. Doubles on each successive
 *  failure up to {@link SSE_RECONNECT_BACKOFF_MAX_MS}; resets on first
 *  successful message. */
export const SSE_RECONNECT_BACKOFF_INITIAL_MS = 1_000;

/** Ceiling for the exponential reconnect backoff (1→2→4→8→16→30s). Keeps
 *  retries from drifting into "the user gave up" territory while still
 *  backing off a hard-down backend. */
export const SSE_RECONNECT_BACKOFF_MAX_MS = 30_000;

/** Below this age, {@link relativeTime} prints "just now" instead of "0s ago"
 *  — date-fns rounds to seconds, which feels jittery at the boundary. */
export const RELATIVE_TIME_JUST_NOW_THRESHOLD_MS = 60_000;
