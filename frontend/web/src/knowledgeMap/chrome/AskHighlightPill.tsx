// On-canvas notice while an Ask answer is lighting the map: what question the
// lit spires answer, how much of the map it touched, and a way to clear it.
// Bottom-centre — the compass owns bottom-left, the Ask bubble bottom-right,
// the hint top-centre and the home button top-right.

import { Sparkles, X } from 'lucide-react';
import { useMapHighlightStore } from '../../app/lib/mapHighlightStore';
import { useKnowledgeMapStore } from '../store';

export function AskHighlightPill() {
  const resolved = useKnowledgeMapStore((s) => s.askHighlight);
  const clear = useMapHighlightStore((s) => s.clear);
  if (!resolved) return null;

  const tags = resolved.tagIds.size;
  const regions = resolved.regionIdxs.size;
  const what =
    tags > 0
      ? `${tags} topic${tags === 1 ? '' : 's'}`
      : regions > 0
        ? `${regions} region${regions === 1 ? '' : 's'}`
        : 'no mapped sources';
  const label = resolved.label.length > 64 ? `${resolved.label.slice(0, 61)}…` : resolved.label;

  return (
    <div
      role="status"
      className="glass-panel absolute bottom-6 left-1/2 z-[5] flex max-w-[min(560px,calc(100%-2rem))] -translate-x-1/2 items-center gap-2.5 rounded-full py-1.5 pl-3.5 pr-1.5 shadow-sm animate-fade-in motion-reduce:animate-none"
    >
      <Sparkles size={13} strokeWidth={1.75} className="shrink-0 text-magenta" aria-hidden />
      <span className="min-w-0 truncate font-sans text-xs text-ink">
        <span className="text-muted">Lit for </span>
        <span className="italic">“{label}”</span>
        <span className="text-muted"> · {what}</span>
      </span>
      <button
        type="button"
        onClick={clear}
        aria-label="Clear the answer highlight"
        title="Clear (Esc)"
        className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-bone/70 hover:text-ink"
      >
        <X size={13} strokeWidth={1.75} aria-hidden />
      </button>
    </div>
  );
}
