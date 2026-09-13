// Floating "show me the whole map" control on the canvas. Back (right panel)
// only pops one nav step and the panel has no nav bar at all at the root, so
// after orbiting / panning away there was no way to recover the overview short
// of reloading. Top-right: the title sits top-left, the hint top-centre, the
// compass bottom-left and the Ask bubble owns bottom-right.

import { Home } from 'lucide-react';
import { useKnowledgeMapStore } from '../store';

export function ResetViewButton() {
  const home = useKnowledgeMapStore((s) => s.home);
  return (
    <button
      type="button"
      onClick={home}
      title="Home: show the whole map"
      aria-label="Home: show the whole map"
      className="glass-panel absolute top-7 right-6 z-[5] grid h-9 w-9 place-items-center rounded-full text-muted shadow-sm transition-colors hover:text-ink hover:bg-bone/70"
    >
      <Home size={16} strokeWidth={1.75} aria-hidden />
    </button>
  );
}
