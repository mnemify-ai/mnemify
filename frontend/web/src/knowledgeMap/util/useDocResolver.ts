// Resolve a map Note to a Documents-DB id.
//
// Map notes (mocknotes / /api/terrain/notes) and the harvested Documents DB use
// DIFFERENT ids (note `n-…` vs doc UUID), so a note id can't be passed to the
// document viewer directly. They DO share titles 1:1, so we join on
// (source + title). The Documents list is react-query cached, so this is a
// single shared fetch regardless of how many notes get opened.

import { useMemo } from 'react';
import { useDocuments } from '../../app/api/documents';
import type { Note } from '../types';

const key = (source: string, title: string) =>
  `${source.trim().toLowerCase()}|${title.trim().toLowerCase()}`;

export function useDocIdForNote(note: Note | null): { docId: string | null; loading: boolean } {
  const q = useDocuments({ limit: 1000 });
  return useMemo(() => {
    if (!note) return { docId: null, loading: false };
    if (q.isLoading && !q.data) return { docId: null, loading: true };
    const rows = q.data?.rows ?? [];
    // Prefer an exact source+title match; fall back to title-only (covers notes
    // whose source label differs slightly from the document's).
    const bySourceTitle = new Map(rows.map((r) => [key(r.source, r.title), r.id]));
    const docId =
      bySourceTitle.get(key(note.source, note.title)) ??
      rows.find((r) => r.title.trim().toLowerCase() === note.title.trim().toLowerCase())?.id ??
      null;
    return { docId, loading: false };
  }, [note, q.data, q.isLoading]);
}
