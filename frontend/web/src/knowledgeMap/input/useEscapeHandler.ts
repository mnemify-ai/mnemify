// Esc key handler — drives the single nav layer:
//   1. If there's nav history, step Back one screen (region ← sub ← tag ← doc).
//   2. Otherwise, if anything is focused/selected, reset to the map root (home) view.
//
// Routing Escape through back()/resetNav() keeps it from becoming a second
// writer of focus/tag/doc that could desync the history (see store.ts).

import { useEffect } from 'react';
import { useKnowledgeMapStore } from '../store';

export function useEscapeHandler() {
  const back = useKnowledgeMapStore((s) => s.back);
  const resetNav = useKnowledgeMapStore((s) => s.resetNav);
  const hasHistory = useKnowledgeMapStore((s) => s.navHistory.length > 0);
  const atRoot = useKnowledgeMapStore(
    (s) => s.focusRegionIdx === null && s.selectedTagId === null && s.docNoteId === null,
  );

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== 'Escape') return;
      if (hasHistory) back();
      else if (!atRoot) resetNav();
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [hasHistory, atRoot, back, resetNav]);
}
