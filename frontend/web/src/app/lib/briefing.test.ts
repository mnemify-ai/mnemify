import { afterEach, describe, expect, it, vi } from "vitest";
import {
  HARVEST_NUDGE_SNOOZE_MS,
  RECENT_HARVEST_MS,
  STALE_HARVEST_MS,
  computeBriefing,
  computeHarvestNudge,
  computePendingLine,
} from "./briefing";
import type { BurningItem, TerrainReport } from "../api/terrain";
import type { ChangeEntry, ChangesSummary } from "../api/changes";

function burning(over: Partial<BurningItem>): BurningItem {
  return {
    id: "tag.x",
    type: "tag",
    label: "X",
    attentionScore: 1,
    attentionLevel: "high",
    signalCount: 1,
    ...over,
  };
}

function report(over: Partial<TerrainReport>): TerrainReport {
  return {
    exists: true,
    generated_at: "2026-06-26T10:00:00Z",
    ai_mode: "openai",
    seconds: 1,
    stats: null,
    highlights: null,
    burning: [],
    compiler: null,
    by_source: {},
    last_run: null,
    ...over,
  };
}

describe("computeBriefing", () => {
  const base = { hasClickedTag: true, ackedAt: null };

  it("returns null when no report / not compiled", () => {
    expect(computeBriefing({ ...base, report: null })).toBeNull();
    expect(computeBriefing({ ...base, report: report({ exists: false }) })).toBeNull();
    expect(computeBriefing({ ...base, report: report({ generated_at: null }) })).toBeNull();
  });

  it("returns null until the user's first tag-click", () => {
    const r = report({ burning: [burning({})] });
    expect(computeBriefing({ report: r, hasClickedTag: false, ackedAt: null })).toBeNull();
    expect(computeBriefing({ report: r, hasClickedTag: true, ackedAt: null })).not.toBeNull();
  });

  it("returns null once this compile has been acknowledged", () => {
    const r = report({ burning: [burning({})], generated_at: "2026-06-26T10:00:00Z" });
    expect(
      computeBriefing({ ...base, report: r, ackedAt: "2026-06-26T10:00:00Z" }),
    ).toBeNull();
    // A newer compile re-opens it.
    expect(
      computeBriefing({ ...base, report: r, ackedAt: "2026-06-25T09:00:00Z" }),
    ).not.toBeNull();
  });

  it("returns null when there's nothing to report", () => {
    expect(
      computeBriefing({ ...base, report: report({ stats: null, burning: [] }) }),
    ).toBeNull();
  });

  it("formats nonzero deltas with signs and skips zeros", () => {
    const r = report({
      stats: {
        regions: 5,
        subRegionsTotal: 2,
        tagsTotal: 40,
        notes: 100,
        sources: 3,
        edges: 50,
        deltas: { notes: 12, tags: 0, edges: -3 },
      },
    });
    const view = computeBriefing({ ...base, report: r });
    expect(view?.deltaChips).toEqual(["+12 notes", "-3 connections"]);
  });

  it("keeps only medium+ attention items, capped at 4", () => {
    const r = report({
      burning: [
        burning({ id: "a", attentionLevel: "critical" }),
        burning({ id: "b", attentionLevel: "high" }),
        burning({ id: "c", attentionLevel: "medium" }),
        burning({ id: "d", attentionLevel: "low" }), // dropped
        burning({ id: "e", attentionLevel: "none" }), // dropped
        burning({ id: "f", attentionLevel: "high" }),
        burning({ id: "g", attentionLevel: "high" }), // beyond cap of 4
      ],
    });
    const view = computeBriefing({ ...base, report: r });
    expect(view?.burning.map((b) => b.id)).toEqual(["a", "b", "c", "f"]);
  });

  it("surfaces on deltas alone even when nothing is hot", () => {
    const r = report({
      burning: [],
      stats: {
        regions: 1,
        subRegionsTotal: 0,
        tagsTotal: 1,
        notes: 1,
        sources: 1,
        edges: 1,
        deltas: { notes: 5, tags: 1, edges: 2 },
      },
    });
    const view = computeBriefing({ ...base, report: r });
    expect(view).not.toBeNull();
    expect(view?.compiledAt).toBe("2026-06-26T10:00:00Z");
  });
});

const NOW = Date.parse("2026-08-13T09:00:00Z");
const HOUR = 60 * 60 * 1000;

function change(over: Partial<ChangeEntry>): ChangeEntry {
  return {
    doc_id: null,
    source_id: "1",
    source: "confluence",
    title: "Doc",
    change: "updated",
    changed_at: null,
    source_modified: null,
    author: null,
    last_modified_by: null,
    url: null,
    space: null,
    ...over,
  };
}

function summary(over: Partial<ChangesSummary>): ChangesSummary {
  return { new: 0, updated: 0, deleted: 0, by_source: {}, ...over };
}

describe("computePendingLine", () => {
  afterEach(() => vi.useRealTimers());

  it("keeps the classic framing without opts (back-compat)", () => {
    expect(computePendingLine(3, [])).toBe("3 pages changed since your last compile");
    expect(computePendingLine(0, [])).toBeNull();
  });

  it("uses harvest-anchored framing when the harvest is recent", () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW); // relativeTime() reads Date.now internally
    const line = computePendingLine(6, [], {
      summary: summary({ new: 4, updated: 2 }),
      lastHarvestTime: new Date(NOW - 3 * HOUR).toISOString(),
      now: NOW,
    });
    expect(line).toBe("Harvested 3h ago · 4 new · 2 updated");
  });

  it("omits zero buckets and includes deletions", () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const line = computePendingLine(2, [], {
      summary: summary({ updated: 1, deleted: 1 }),
      lastHarvestTime: new Date(NOW - 1 * HOUR).toISOString(),
      now: NOW,
    });
    expect(line).toBe("Harvested 1h ago · 1 updated · 1 deleted");
  });

  it("falls back to classic framing when the harvest is old", () => {
    const line = computePendingLine(6, [], {
      summary: summary({ new: 6 }),
      lastHarvestTime: new Date(NOW - RECENT_HARVEST_MS - HOUR).toISOString(),
      now: NOW,
    });
    expect(line).toBe("6 pages changed since your last compile");
  });

  it("keeps the attribution clause in both framings", () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const changes = [
      change({ source_id: "1", last_modified_by: "Sarah Chen" }),
      change({ source_id: "2", last_modified_by: "Sarah Chen" }),
      change({ source_id: "3", last_modified_by: "Tom Ito" }),
    ];
    expect(computePendingLine(3, changes)).toBe(
      "3 pages changed since your last compile — 2 by Sarah Chen",
    );
    expect(
      computePendingLine(3, changes, {
        summary: summary({ new: 3 }),
        lastHarvestTime: new Date(NOW - HOUR).toISOString(),
        now: NOW,
      }),
    ).toBe("Harvested 1h ago · 3 new — 2 by Sarah Chen");
  });
});

describe("computeHarvestNudge", () => {
  const base = {
    lastHarvestTime: new Date(NOW - STALE_HARVEST_MS - HOUR).toISOString(),
    scheduleEnabled: false,
    harvestRunning: false,
    pendingTotal: 0,
    snoozedUntil: null,
    now: NOW,
  };

  it("nudges when the last harvest is stale", () => {
    const nudge = computeHarvestNudge(base);
    expect(nudge).not.toBeNull();
    expect(nudge?.suggestSchedule).toBe(true);
  });

  it("does not suggest a schedule when one is enabled", () => {
    expect(computeHarvestNudge({ ...base, scheduleEnabled: true })?.suggestSchedule).toBe(
      false,
    );
  });

  it("returns null when never harvested", () => {
    expect(computeHarvestNudge({ ...base, lastHarvestTime: null })).toBeNull();
    expect(computeHarvestNudge({ ...base, lastHarvestTime: "garbage" })).toBeNull();
  });

  it("returns null when the last harvest is fresh", () => {
    expect(
      computeHarvestNudge({
        ...base,
        lastHarvestTime: new Date(NOW - HOUR).toISOString(),
      }),
    ).toBeNull();
  });

  it("returns null while a harvest is running", () => {
    expect(computeHarvestNudge({ ...base, harvestRunning: true })).toBeNull();
  });

  it("returns null when uncompiled changes exist (compile ask wins)", () => {
    expect(computeHarvestNudge({ ...base, pendingTotal: 5 })).toBeNull();
  });

  it("respects an active snooze and expires it", () => {
    expect(
      computeHarvestNudge({ ...base, snoozedUntil: NOW + HARVEST_NUDGE_SNOOZE_MS }),
    ).toBeNull();
    expect(computeHarvestNudge({ ...base, snoozedUntil: NOW - 1 })).not.toBeNull();
  });
});
