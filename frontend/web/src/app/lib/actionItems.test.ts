import { describe, expect, it } from "vitest";
import type { ActionItem } from "../api/actionItems";
import { cleanTitle, dueLabel, partitionActionItems, pruneDismissed, staleContext } from "./actionItems";

function item(id: string, overrides: Partial<ActionItem> = {}): ActionItem {
  return {
    id,
    title: `Todo: ${id}`,
    summary: "",
    severity: 50,
    status: "open",
    owner: null,
    due_date: null,
    due_text: null,
    days_until_due: null,
    bucket: "no_date",
    source_note_ids: [],
    source_chunk_ids: [],
    region_id: null,
    region_label: null,
    tag_id: null,
    tag_label: null,
    ...overrides,
  };
}

const TODAY = "2026-08-10";

describe("partitionActionItems", () => {
  it("splits by bucket and preserves server order within each", () => {
    const items = [
      item("a", { bucket: "overdue", due_date: "2026-08-01" }),
      item("b", { bucket: "overdue", due_date: "2026-08-05" }),
      item("c", { bucket: "due_soon", due_date: "2026-08-14" }),
      item("d", { bucket: "upcoming", due_date: "2026-09-01" }),
      item("e"),
    ];
    const parts = partitionActionItems(items, new Set());
    expect(parts.overdue.map((i) => i.id)).toEqual(["a", "b"]);
    expect(parts.dueSoon.map((i) => i.id)).toEqual(["c"]);
    expect(parts.upcoming.map((i) => i.id)).toEqual(["d"]);
    expect(parts.noDate.map((i) => i.id)).toEqual(["e"]);
    expect(parts.dismissedCount).toBe(0);
  });

  it("filters dismissed items and counts them", () => {
    const items = [
      item("a", { bucket: "overdue", due_date: "2026-08-01" }),
      item("b", { bucket: "due_soon", due_date: "2026-08-14" }),
    ];
    const parts = partitionActionItems(items, new Set(["a"]));
    expect(parts.overdue).toEqual([]);
    expect(parts.dueSoon.map((i) => i.id)).toEqual(["b"]);
    expect(parts.dismissedCount).toBe(1);
  });
});

describe("pruneDismissed", () => {
  it("drops ids that no longer exist in the compiled map", () => {
    const pruned = pruneDismissed(new Set(["live", "gone"]), [item("live")]);
    expect([...pruned]).toEqual(["live"]);
  });
});

describe("cleanTitle", () => {
  it("drops the kind prefix", () => {
    expect(cleanTitle("Todo: send the packet")).toBe("send the packet");
  });

  it("strips blockquote/list markers and markdown emphasis", () => {
    expect(
      cleanTitle("> **If you need to hit real internal APIs** (Exporter), set `EXPORTE"),
    ).toBe("If you need to hit real internal APIs (Exporter), set EXPORTE");
    expect(cleanTitle("- *Ship the harvester*")).toBe("Ship the harvester");
  });

  it("collapses whitespace", () => {
    expect(cleanTitle("Todo:  fix   the \t thing")).toBe("fix the thing");
  });
});

describe("dueLabel", () => {
  it("labels overdue with day count", () => {
    expect(dueLabel(item("a", { due_date: "2026-08-01" }), TODAY)).toBe("Overdue 9d");
  });

  it("labels today and tomorrow", () => {
    expect(dueLabel(item("a", { due_date: "2026-08-10" }), TODAY)).toBe("Due today");
    expect(dueLabel(item("a", { due_date: "2026-08-11" }), TODAY)).toBe("Due tomorrow");
  });

  it("uses the weekday inside a week", () => {
    // 2026-08-14 is a Friday; TODAY (2026-08-10) is a Monday.
    expect(dueLabel(item("a", { due_date: "2026-08-14" }), TODAY)).toBe("Due Fri");
  });

  it("uses month + day beyond a week, adding the year when it differs", () => {
    expect(dueLabel(item("a", { due_date: "2026-09-30" }), TODAY)).toBe("Due Sep 30");
    expect(dueLabel(item("a", { due_date: "2027-01-05" }), TODAY)).toBe("Due Jan 5, 2027");
  });

  it("falls back to the verbatim phrase, then null", () => {
    expect(dueLabel(item("a", { due_text: "before the offsite" }), TODAY)).toBe(
      "Due before the offsite",
    );
    expect(dueLabel(item("a"), TODAY)).toBeNull();
  });
});

describe("probably abandoned", () => {
  it("partitions into its own section", () => {
    const parts = partitionActionItems(
      [
        item("a", { bucket: "overdue", due_date: "2026-08-01" }),
        item("b", { bucket: "probably_abandoned", due_date: "2024-05-31" }),
      ],
      new Set(),
    );
    expect(parts.overdue.map((i) => i.id)).toEqual(["a"]);
    expect(parts.probablyAbandoned.map((i) => i.id)).toEqual(["b"]);
  });

  it("labels with the date instead of a day count", () => {
    expect(dueLabel(item("a", { bucket: "probably_abandoned", due_date: "2024-05-31" }), TODAY)).toBe(
      "Was due May 31, 2024",
    );
    expect(dueLabel(item("a", { bucket: "probably_abandoned", due_date: "2026-03-08" }), TODAY)).toBe(
      "Was due Mar 8",
    );
  });

  it("describes when the source note was last edited", () => {
    const stale = (extra: Partial<ActionItem>) =>
      staleContext(item("a", { bucket: "probably_abandoned", due_date: "2025-09-12", ...extra }), TODAY);
    expect(stale({ note_updated_at: "2026-02-13T13:54:41Z" })).toBe("note edited Feb 13, 5mo after");
    expect(stale({ note_updated_at: "2025-09-15T00:00:00Z" })).toBe("note edited Sep 15, 2025, 3d after");
    expect(stale({ note_updated_at: "2025-06-24T11:01:12Z" })).toBe(
      "note edited Jun 24, 2025, before the deadline",
    );
    expect(stale({ note_updated_at: null })).toBeNull();
    expect(staleContext(item("a", { bucket: "overdue", due_date: "2026-08-01", note_updated_at: "2026-08-05" }), TODAY)).toBeNull();
  });
});
