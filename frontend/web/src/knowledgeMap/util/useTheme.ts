// Read-only theme observer for the KnowledgeMap. Watches `<html>`'s class
// list and re-renders subscribers when `.dark` toggles. We deliberately
// don't import `useThemeMode` from app/lib — that hook owns the *writer*
// and persistence; this one is a passive listener so the map stays
// decoupled from where the toggle lives.

import { useEffect, useState } from 'react';

export type Theme = 'light' | 'dark';

function readTheme(): Theme {
  if (typeof document === 'undefined') return 'light';
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light';
}

export function useTheme(): Theme {
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => {
    if (typeof document === 'undefined') return;
    const root = document.documentElement;

    const sync = () => {
      const next = readTheme();
      setTheme((prev) => (prev === next ? prev : next));
    };

    const observer = new MutationObserver(sync);
    observer.observe(root, { attributes: true, attributeFilter: ['class'] });
    sync();

    return () => observer.disconnect();
  }, []);

  return theme;
}
