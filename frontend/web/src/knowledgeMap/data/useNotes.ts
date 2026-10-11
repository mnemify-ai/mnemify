// Lazy-load mocknotes.json on first sidebar open. ~800 KB so we don't
// fetch it at boot — only when the user actually clicks a tag.

import { useEffect, useState } from 'react';
import type { Note, NotesFile } from '../types';

export type NotesState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'ready'; notes: Note[]; byTagId: Map<string, Note[]> };

// Keyed by URL: the sample map and the real map serve different notes files,
// and whichever loaded first must not answer for the other.
const cachedPromises = new Map<string, Promise<NotesFile>>();

function fetchNotes(url: string): Promise<NotesFile> {
  const cached = cachedPromises.get(url);
  if (cached) return cached;
  const promise = fetch(url).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status} fetching ${url}`);
    return r.json() as Promise<NotesFile>;
  });
  // Don't pin a failure — let the next caller retry.
  promise.catch(() => cachedPromises.delete(url));
  cachedPromises.set(url, promise);
  return promise;
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
