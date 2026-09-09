import { describe, expect, it } from "vitest";
import {
  mergePulses,
  nextExpiry,
  prunePulses,
  PULSE_TTL_MS,
  type PulseMap,
} from "./mapPulseStore";

describe("mergePulses", () => {
  it("stamps each id with an expiry ttl from now", () => {
    expect(mergePulses({}, ["a", "b"], 1000)).toEqual({
      a: 1000 + PULSE_TTL_MS,
      b: 1000 + PULSE_TTL_MS,
    });
  });

  it("extends a region that pulses again", () => {
    const first = mergePulses({}, ["a"], 1000, 500);
    expect(mergePulses(first, ["a"], 1200, 500)).toEqual({ a: 1700 });
  });

  it("returns the same object for an empty or missing step payload", () => {
    const prev: PulseMap = { a: 5 };
    expect(mergePulses(prev, [], 0)).toBe(prev);
    expect(mergePulses(prev, undefined, 0)).toBe(prev);
  });
});

describe("prunePulses", () => {
  it("drops only what has expired", () => {
    expect(prunePulses({ a: 100, b: 300 }, 200)).toEqual({ b: 300 });
  });

  it("keeps object identity when nothing expired — the prune timer repeats", () => {
    const prev: PulseMap = { a: 100 };
    expect(prunePulses(prev, 50)).toBe(prev);
  });
});

describe("nextExpiry", () => {
  it("is the soonest deadline, or null when idle", () => {
    expect(nextExpiry({ a: 300, b: 100, c: 200 })).toBe(100);
    expect(nextExpiry({})).toBeNull();
  });
});
