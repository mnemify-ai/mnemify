import { describe, it, expect } from "vitest";
import { formatEta, computeEtaSeconds, formatDuration } from "./formatEta";

describe("computeEtaSeconds", () => {
  it("returns null when the rate is missing or non-positive", () => {
    expect(computeEtaSeconds(0, 10, null)).toBeNull();
    expect(computeEtaSeconds(0, 10, 0)).toBeNull();
    expect(computeEtaSeconds(0, 10, -1)).toBeNull();
    expect(computeEtaSeconds(0, 10, undefined)).toBeNull();
  });

  it("returns 0 when nothing is remaining", () => {
    expect(computeEtaSeconds(10, 10, 2)).toBe(0);
    expect(computeEtaSeconds(12, 10, 2)).toBe(0);
  });

  it("returns remaining / rate", () => {
    expect(computeEtaSeconds(0, 10, 2)).toBe(5);
    expect(computeEtaSeconds(6, 10, 2)).toBe(2);
  });
});

describe("formatEta", () => {
  it("formats seconds, minutes, and hours compactly", () => {
    expect(formatEta(17)).toBe("17s");
    expect(formatEta(0.4)).toBe("0s");
    expect(formatEta(83)).toBe("1m 23s");
    expect(formatEta(120)).toBe("2m");
    expect(formatEta(3720)).toBe("1h 2m");
    expect(formatEta(3600)).toBe("1h");
  });

  it("renders an em dash for invalid inputs", () => {
    expect(formatEta(null)).toBe("—");
    expect(formatEta(undefined)).toBe("—");
    expect(formatEta(-1)).toBe("—");
    expect(formatEta(Infinity)).toBe("—");
    expect(formatEta(NaN)).toBe("—");
  });
});

describe("formatDuration", () => {
  it("formats sub-minute, minute, and hour durations", () => {
    expect(formatDuration(45)).toBe("45s");
    expect(formatDuration(90)).toBe("1m 30s");
    expect(formatDuration(3720)).toBe("1h 2m");
    expect(formatDuration(null)).toBe("—");
  });
});
