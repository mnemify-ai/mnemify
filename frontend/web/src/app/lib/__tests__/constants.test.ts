import { describe, it, expect } from "vitest";
import {
  LOG_TAIL_BUFFER_LIMIT,
  RATE_EWMA_ALPHA,
  RELATIVE_TIME_JUST_NOW_THRESHOLD_MS,
  SSE_RECONNECT_BACKOFF_INITIAL_MS,
  SSE_RECONNECT_BACKOFF_MAX_MS,
} from "../constants";

describe("constants — behavioral invariants", () => {
  it("LOG_TAIL_BUFFER_LIMIT is a positive integer", () => {
    // The reducer slices `.slice(0, LIMIT)` — a zero or negative limit would
    // silently drop every log line.
    expect(Number.isInteger(LOG_TAIL_BUFFER_LIMIT)).toBe(true);
    expect(LOG_TAIL_BUFFER_LIMIT).toBeGreaterThan(0);
  });

  it("RATE_EWMA_ALPHA is a proper smoothing weight strictly between 0 and 1", () => {
    // α === 0 → the rate would never update; α === 1 → no smoothing at all.
    // Either degenerate case defeats the point of the EWMA.
    expect(RATE_EWMA_ALPHA).toBeGreaterThan(0);
    expect(RATE_EWMA_ALPHA).toBeLessThan(1);
  });

  it("SSE reconnect backoff bounds are sane (initial < max, both positive)", () => {
    expect(SSE_RECONNECT_BACKOFF_INITIAL_MS).toBeGreaterThan(0);
    expect(SSE_RECONNECT_BACKOFF_MAX_MS).toBeGreaterThan(SSE_RECONNECT_BACKOFF_INITIAL_MS);
  });

  it("RELATIVE_TIME_JUST_NOW_THRESHOLD_MS is positive", () => {
    // A zero threshold would mean "just now" never fires; a negative one would
    // make every timestamp print "just now".
    expect(RELATIVE_TIME_JUST_NOW_THRESHOLD_MS).toBeGreaterThan(0);
  });
});
