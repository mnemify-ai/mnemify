// Pure helpers behind "Save selection to memory" — kept DOM-free so they run
// under the node-only vitest config. The hook (`useSelectionInside`) feeds
// them real Range/Node objects.

/** Trim and collapse a selection's text; null when nothing worth saving. */
export function normalizeSelection(raw: string | null | undefined): string | null {
  const text = (raw ?? "").replace(/\r/g, "").replace(/[ \t]+\n/g, "\n").trim();
  if (text.length < 3) return null;
  return text;
}

/** Walk up from `node` until `isMessage` says yes; returns the message id. */
export function messageIdFor(
  node: { parentNode: unknown | null; dataset?: Record<string, string | undefined> } | null,
  isInside: (n: unknown) => boolean,
): string | null {
  let cur: typeof node = node;
  while (cur) {
    if (cur.dataset?.messageId && isInside(cur)) return cur.dataset.messageId;
    cur = cur.parentNode as typeof node;
  }
  return null;
}
