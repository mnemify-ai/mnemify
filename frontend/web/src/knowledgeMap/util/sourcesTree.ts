// The right panel's Sources view: every mapped note grouped the way it lives
// in its source — Notion parent pages, Confluence spaces, vault and local
// folders — rather than by region. Pure so it can be unit-tested and so the
// sample workspace and a real compiled map build it the same way.

import type { Note } from '../types';

export type SourceTreeGroup = {
  kind: 'group';
  /** Stable, unique across the whole tree: source + path. Used for expand state. */
  key: string;
  label: string;
  /** Notes anywhere below this group. */
  count: number;
  /** A page that is ALSO a container (a Notion parent page). Clicking the
   *  group's label opens it; its children list underneath. */
  note: Note | null;
  children: SourceTreeNode[];
};

export type SourceTreeLeaf = { kind: 'note'; key: string; note: Note };

export type SourceTreeNode = SourceTreeGroup | SourceTreeLeaf;

export type SourceTreeRoot = {
  source: string;
  key: string;
  count: number;
  children: SourceTreeNode[];
};

/** Container path for a note: the compiler's `docPath`, else the source's
 *  one-level container (`sourceDetail`, e.g. a Confluence space), else none. */
export function notePath(note: Note): string[] {
  if (note.docPath && note.docPath.length > 0) return note.docPath.filter((p) => p.trim() !== '');
  if (note.sourceDetail) return [note.sourceDetail];
  return [];
}

type MutableGroup = {
  key: string;
  label: string;
  note: Note | null;
  groups: Map<string, MutableGroup>;
  notes: Note[];
};

function newGroup(key: string, label: string): MutableGroup {
  return { key, label, note: null, groups: new Map(), notes: [] };
}

// Joins path segments in keys. Titles can contain "/", so use a character
// they can't: ["Q3/Q4"] and ["Q3", "Q4"] must not share expand state.
const KEY_SEP = '\u001f';

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

function finish(g: MutableGroup): { children: SourceTreeNode[]; count: number } {
  // A note whose title matches a sibling container IS that container's page
  // (a Notion parent page and its children) — fold it into the group.
  const leaves: Note[] = [];
  for (const n of g.notes) {
    const asGroup = g.groups.get(n.title);
    if (asGroup && asGroup.note === null) asGroup.note = n;
    else leaves.push(n);
  }
  const groups = [...g.groups.values()]
    .map((child): SourceTreeGroup => {
      const done = finish(child);
      return {
        kind: 'group',
        key: child.key,
        label: child.label,
        note: child.note,
        children: done.children,
        count: done.count + (child.note ? 1 : 0),
      };
    })
    .sort((a, b) => collator.compare(a.label, b.label));
  const notes = leaves
    .sort((a, b) => collator.compare(a.title, b.title))
    .map((note): SourceTreeLeaf => ({ kind: 'note', key: `note:${note.id}`, note }));
  const count = groups.reduce((n, c) => n + c.count, 0) + notes.length;
  // Containers first, like a file browser.
  return { children: [...groups, ...notes], count };
}

/** Group notes into source → container path → note. Sources are ordered by
 *  size (largest first); groups and notes alphabetically (numeric-aware, so
 *  "ADR-9" sorts before "ADR-24"). */
export function buildSourcesTree(notes: readonly Note[]): SourceTreeRoot[] {
  const roots = new Map<string, MutableGroup>();
  for (const note of notes) {
    const source = note.source || 'unknown';
    let cur = roots.get(source);
    if (!cur) {
      cur = newGroup(`src:${source}`, source);
      roots.set(source, cur);
    }
    for (const label of notePath(note)) {
      const key = `${cur.key}${KEY_SEP}${label}`;
      let next = cur.groups.get(label);
      if (!next) {
        next = newGroup(key, label);
        cur.groups.set(label, next);
      }
      cur = next;
    }
    cur.notes.push(note);
  }
  return [...roots.entries()]
    .map(([source, g]) => {
      const done = finish(g);
      return { source, key: g.key, count: done.count, children: done.children };
    })
    .sort((a, b) => b.count - a.count || collator.compare(a.source, b.source));
}

/** Keys of every group on the way to `noteId` (to reveal it), or null when the
 *  note isn't in the tree. */
export function pathKeysTo(roots: readonly SourceTreeRoot[], noteId: string): string[] | null {
  const walk = (nodes: readonly SourceTreeNode[], trail: string[]): string[] | null => {
    for (const n of nodes) {
      if (n.kind === 'note') {
        if (n.note.id === noteId) return trail;
        continue;
      }
      if (n.note?.id === noteId) return trail;
      const hit = walk(n.children, [...trail, n.key]);
      if (hit) return hit;
    }
    return null;
  };
  for (const r of roots) {
    const hit = walk(r.children, [r.key]);
    if (hit) return hit;
  }
  return null;
}

/** Prune the tree to notes whose title matches `query` (case-insensitive),
 *  keeping their containers. Returns the pruned roots and the keys of every
 *  surviving group so the caller can show matches expanded. */
export function filterSourcesTree(
  roots: readonly SourceTreeRoot[],
  query: string,
): { roots: SourceTreeRoot[]; openKeys: Set<string> } {
  const q = query.trim().toLowerCase();
  const openKeys = new Set<string>();
  if (!q) return { roots: [...roots], openKeys };
  const hit = (n: Note) => n.title.toLowerCase().includes(q);
  const prune = (nodes: readonly SourceTreeNode[]): SourceTreeNode[] => {
    const out: SourceTreeNode[] = [];
    for (const n of nodes) {
      if (n.kind === 'note') {
        if (hit(n.note)) out.push(n);
        continue;
      }
      const children = prune(n.children);
      const selfHit = n.note !== null && hit(n.note);
      if (children.length === 0 && !selfHit) continue;
      openKeys.add(n.key);
      out.push({ ...n, children, count: countNotes(children) + (selfHit ? 1 : 0) });
    }
    return out;
  };
  const pruned: SourceTreeRoot[] = [];
  for (const r of roots) {
    const children = prune(r.children);
    if (children.length === 0) continue;
    openKeys.add(r.key);
    pruned.push({ ...r, children, count: countNotes(children) });
  }
  return { roots: pruned, openKeys };
}

function countNotes(nodes: readonly SourceTreeNode[]): number {
  return nodes.reduce((n, c) => n + (c.kind === 'note' ? 1 : c.count), 0);
}
