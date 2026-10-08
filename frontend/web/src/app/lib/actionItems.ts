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
  /** Open items whose deadline passed long ago — stale, not alarming. */
  probablyAbandoned: ActionItem[];
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
    probablyAbandoned: [],
    dismissedCount: 0,
  };
  const byBucket: Record<ActionItemBucket, ActionItem[]> = {
    overdue: out.overdue,
    due_soon: out.dueSoon,
    upcoming: out.upcoming,
    no_date: out.noDate,
    probably_abandoned: out.probablyAbandoned,
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

function monthDay(d: Date, now: Date): string {
  const md = `${MONTH[d.getUTCMonth()]} ${d.getUTCDate()}`;
  return d.getUTCFullYear() === now.getUTCFullYear() ? md : `${md}, ${d.getUTCFullYear()}`;
}

/**
 * Short human label for an item's deadline: "Overdue 3d" / "Due today" /
 * "Due tomorrow" / "Due Fri" (inside a week) / "Due Apr 30" / "Due Apr 30, 2027".
 * A probably-abandoned item reads "Was due May 31, 2024" — a day count in the
 * hundreds is noise, the date itself is the useful fact.
 * Falls back to the verbatim source phrase for items with no resolved date.
 */
export function dueLabel(item: ActionItem, today: string): string | null {
  if (!item.due_date) return item.due_text ? `Due ${item.due_text}` : null;
  const due = parseIsoDate(item.due_date);
  const now = parseIsoDate(today);
  if (!due || !now) return `Due ${item.due_date}`;
  if (item.bucket === "probably_abandoned") return `Was due ${monthDay(due, now)}`;
  const days = Math.round((due.getTime() - now.getTime()) / 86_400_000);
  if (days < 0) return `Overdue ${-days}d`;
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  if (days < 7) return `Due ${WEEKDAY[due.getUTCDay()]}`;
  return `Due ${monthDay(due, now)}`;
}

/**
 * Context line for a stale item: when its source note was last edited,
 * relative to the deadline — "note edited Feb 13, 2026, 5 months after" tells
 * the user the page kept moving past the deadline (likely done or dropped);
 * "note edited May 21, 2024, before the deadline" says nobody came back.
 * Null when the edit date is unknown or the item isn't stale.
 */
export function staleContext(item: ActionItem, today: string): string | null {
  if (item.bucket !== "probably_abandoned" || !item.due_date || !item.note_updated_at) return null;
  const due = parseIsoDate(item.due_date);
  const edited = parseIsoDate(item.note_updated_at);
  const now = parseIsoDate(today);
  if (!due || !edited || !now) return null;
  const when = `note edited ${monthDay(edited, now)}`;
  const days = Math.round((edited.getTime() - due.getTime()) / 86_400_000);
  if (days <= 0) return `${when}, before the deadline`;
  const months = Math.round(days / 30);
  const after =
    days < 14 ? `${days}d after` : months < 1 ? "weeks after" : `${months}mo after`;
  return `${when}, ${after}`;
}
