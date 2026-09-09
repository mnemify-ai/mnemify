// Lazy-load mocknotes.json on first sidebar open. ~800 KB so we don't
// fetch it at boot — only when the user actually clicks a tag.

import { useEffect, useState } from 'react';
import type { Note, NotesFile } from '../types';

export type NotesState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'ready'; notes: Note[]; byTagId: Map<string, Note[]> };

let cachedPromise: Promise<NotesFile> | null = null;

function fetchNotes(url: string): Promise<NotesFile> {
  if (cachedPromise) return cachedPromise;
  cachedPromise = fetch(url)
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status} fetching ${url}`);
      return r.json();
    });
  return cachedPromise;
}

/** Fetches mocknotes.json on demand and indexes notes by tag id. */
export function useNotes(url: string, enabled: boolean): NotesState {
  const [state, setState] = useState<NotesState>({ status: 'idle' });

  useEffect(() => {
    if (!enabled) return;
    if (state.status === 'ready' || state.status === 'loading') return;
    let cancelled = false;
    setState({ status: 'loading' });
    fetchNotes(url)
      .then((file) => {
        if (cancelled) return;
        const byTagId = new Map<string, Note[]>();
        for (const n of file.notes) {
          for (const tagId of n.tagIds) {
            const arr = byTagId.get(tagId) ?? [];
            arr.push(n);
            byTagId.set(tagId, arr);
          }
        }
        setState({ status: 'ready', notes: file.notes, byTagId });
      })
      .catch((e) => {
        if (cancelled) return;
        setState({ status: 'error', error: String(e) });
      });
    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, enabled]);

  return state;
}
