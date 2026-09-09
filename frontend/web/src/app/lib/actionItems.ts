// Pure shaping logic for the Action Items page: dismissal persistence,
// bucket partitioning, and due-date labels. Kept separate from the JSX so it
// can be unit-tested without a DOM (the test env is node-only — see
// vitest.config.ts and lib/briefing.ts for the same pattern).

import type { ActionItem, ActionItemBucket } from "../api/actionItems";

/** Signal ids the user dismissed. Ids are stable content hashes, so a
 * dismissal survives recompiles for as long as the source text is unchanged. */
const DISMISSED_KEY = "mnemify.actionItems.dismissed";

export function loadDismissed(): Set<string> {
  if (typeof localStorage === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(DISMISSED_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.filter((v) => typeof v === "string") : []);
  } catch {
    return new Set();
  }
}

export function saveDismissed(ids: Set<string>): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(DISMISSED_KEY, JSON.stringify([...ids]));
  } catch {
    /* quota/private mode — dismissal just won't persist */
  }
}

/** Drop dismissed ids that no longer exist in the compiled map (the source
 * line was removed or reworded), so the stored set can't grow forever. */
export function pruneDismissed(dismissed: Set<string>, items: ActionItem[]): Set<string> {
  const live = new Set(items.map((it) => it.id));
  return new Set([...dismissed].filter((id) => live.has(id)));
}

export interface PartitionedActionItems {
  overdue: ActionItem[];
  dueSoon: ActionItem[];
  upcoming: ActionItem[];
  noDate: ActionItem[];
  /** How many live items the user has dismissed (for a "N dismissed" note). */
  dismissedCount: number;
}

/** Split the (already sorted) item list into bucket sections, minus dismissed. */
export function partitionActionItems(
  items: ActionItem[],
  dismissed: ReadonlySet<string>,
): PartitionedActionItems {
  const out: PartitionedActionItems = {
    overdue: [],
    dueSoon: [],
    upcoming: [],
    noDate: [],
    dismissedCount: 0,
  };
  const byBucket: Record<ActionItemBucket, ActionItem[]> = {
    overdue: out.overdue,
    due_soon: out.dueSoon,
    upcoming: out.upcoming,
    no_date: out.noDate,
  };
  for (const item of items) {
    if (dismissed.has(item.id)) {
      out.dismissedCount += 1;
      continue;
    }
    byBucket[item.bucket].push(item);
  }
  return out;
}

/**
 * Normalize an extracted signal title for display: drop the "Todo:" kind
 * prefix, blockquote/list markers, and markdown emphasis/code markers.
 * Old compiled maps (pre-deadline pipeline) carry raw source lines here.
 */
export function cleanTitle(raw: string): string {
  return raw
    .replace(/^\s*(todo|risk|decision|open question|owner|recent change):\s*/i, "")
    .replace(/^[>\s\-*#]+/, "")
    .replace(/[*_`]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

const WEEKDAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function parseIsoDate(iso: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return null;
  return new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
}

/**
 * Short human label for an item's deadline: "Overdue 3d" / "Due today" /
 * "Due tomorrow" / "Due Fri" (inside a week) / "Due Apr 30" / "Due Apr 30, 2027".
 * Falls back to the verbatim source phrase for items with no resolved date.
 */
export function dueLabel(item: ActionItem, today: string): string | null {
  if (!item.due_date) return item.due_text ? `Due ${item.due_text}` : null;
  const due = parseIsoDate(item.due_date);
  const now = parseIsoDate(today);
  if (!due || !now) return `Due ${item.due_date}`;
  const days = Math.round((due.getTime() - now.getTime()) / 86_400_000);
  if (days < 0) return `Overdue ${-days}d`;
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  if (days < 7) return `Due ${WEEKDAY[due.getUTCDay()]}`;
  const md = `${MONTH[due.getUTCMonth()]} ${due.getUTCDate()}`;
  return due.getUTCFullYear() === now.getUTCFullYear()
    ? `Due ${md}`
    : `Due ${md}, ${due.getUTCFullYear()}`;
}
