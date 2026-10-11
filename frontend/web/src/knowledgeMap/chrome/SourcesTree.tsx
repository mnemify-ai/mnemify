// Sources view of the right panel: every mapped document in the tree it lives
// in at its source (Notion pages, Confluence spaces, vault and local folders).
// The Regions view answers "what is this about"; this answers "where is it".
// Clicking a document opens it in DocDetail, exactly like a note card.

import { useMemo, useState } from 'react';
import { ChevronRight, FileText, Search } from 'lucide-react';
import { useMapData } from '../../app/data/MapDataProvider';
import { sourceMeta } from '../../app/components/SourceBadge';
import { useKnowledgeMapStore } from '../store';
import type { Note } from '../types';
import { buildSourcesTree, filterSourcesTree, type SourceTreeNode } from '../util/sourcesTree';
import { emptyCls } from './panelShared';

const INDENT_PX = 14;

const rowBaseCls =
  'flex items-center gap-1.5 w-full min-w-0 py-[4px] pr-1.5 border-none rounded-md bg-transparent ' +
  'text-left cursor-pointer transition-colors duration-100 hover:bg-ink/[0.06]';

function shortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function SourcesTree() {
  const notes = useMapData().data?.notes.notes;
  const open = useKnowledgeMapStore((s) => s.sourcesOpen);
  const setOpen = useKnowledgeMapStore((s) => s.setSourcesOpen);
  const navigate = useKnowledgeMapStore((s) => s.navigate);
  const [query, setQuery] = useState('');

  const tree = useMemo(() => buildSourcesTree(notes ?? []), [notes]);
  const filtered = useMemo(() => filterSourcesTree(tree, query), [tree, query]);
  const searching = query.trim() !== '';

  if (!notes || notes.length === 0) {
    return <div className={emptyCls}>No documents on this map yet.</div>;
  }

  const isOpen = (key: string) => (searching ? filtered.openKeys.has(key) : open.has(key));
  const toggle = (key: string) => {
    if (searching) return; // search results show fully expanded
    const next = new Set(open);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setOpen(next);
  };
  const openNote = (note: Note) => navigate({ docNoteId: note.id });

  const renderNodes = (nodes: readonly SourceTreeNode[], depth: number) =>
    nodes.map((n) => {
      const pad = { paddingLeft: 4 + depth * INDENT_PX };
      if (n.kind === 'note') {
        return (
          <button
            key={n.key}
            type="button"
            className={`${rowBaseCls} text-ink/[0.85]`}
            style={pad}
            onClick={() => openNote(n.note)}
            title={n.note.title}
          >
            <span className="w-[14px] shrink-0" aria-hidden />
            <FileText size={12} strokeWidth={1.75} className="shrink-0 text-muted" aria-hidden />
            <span className="flex-1 truncate text-[12.5px]">{n.note.title}</span>
            <span className="shrink-0 text-[10px] text-muted tabular-nums">{shortDate(n.note.updatedAt)}</span>
          </button>
        );
      }
      const expanded = isOpen(n.key);
      return (
        <div key={n.key}>
          <div className="flex items-center min-w-0" style={pad}>
            <button
              type="button"
              aria-expanded={expanded}
              aria-label={`${expanded ? 'Collapse' : 'Expand'} ${n.label}`}
              className="grid place-items-center w-[18px] h-[22px] shrink-0 border-none bg-transparent cursor-pointer text-muted hover:text-ink"
              onClick={() => toggle(n.key)}
            >
              <ChevronRight
                size={12}
                strokeWidth={2}
                className={`transition-transform duration-100 ${expanded ? 'rotate-90' : ''}`}
              />
            </button>
            <button
              type="button"
              className={`${rowBaseCls} pl-0.5 text-ink`}
              // A Notion parent page opens on click; a plain container toggles.
              onClick={() => (n.note ? openNote(n.note) : toggle(n.key))}
              title={n.note ? `Open ${n.label}` : n.label}
            >
              <span className="flex-1 truncate text-[12.5px] font-medium">{n.label}</span>
              <span className="shrink-0 text-[10px] text-muted tabular-nums">{n.count}</span>
            </button>
          </div>
          {expanded && renderNodes(n.children, depth + 1)}
        </div>
      );
    });

  return (
    <section className="flex flex-col gap-2">
      <label className="flex items-center gap-1.5 px-2 py-[5px] rounded-md border border-line/25 bg-bone/40 text-muted focus-within:border-magenta/50">
        <Search size={12} strokeWidth={2} aria-hidden />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter documents"
          aria-label="Filter documents by title"
          className="flex-1 min-w-0 bg-transparent border-none outline-none text-[12.5px] text-ink placeholder:text-muted"
        />
      </label>
      {filtered.roots.length === 0 && <div className={emptyCls}>No documents match “{query.trim()}”.</div>}
      <div className="flex flex-col">
        {filtered.roots.map((root) => {
          const meta = sourceMeta(root.source);
          const expanded = isOpen(root.key);
          return (
            <div key={root.key} className="mb-1">
              <button
                type="button"
                aria-expanded={expanded}
                className={`${rowBaseCls} pl-1 text-ink`}
                onClick={() => toggle(root.key)}
              >
                <ChevronRight
                  size={12}
                  strokeWidth={2}
                  className={`shrink-0 text-muted transition-transform duration-100 ${expanded ? 'rotate-90' : ''}`}
                />
                <span className={`w-2 h-2 rounded-full shrink-0 ${meta.dotClass}`} aria-hidden />
                <span className="flex-1 truncate text-[13px] font-semibold">{meta.label}</span>
                <span className="shrink-0 text-[10px] text-muted tabular-nums">{root.count}</span>
              </button>
              {expanded && renderNodes(root.children, 1)}
            </div>
          );
        })}
      </div>
    </section>
  );
}
