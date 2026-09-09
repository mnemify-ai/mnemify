// Hover tooltip for hex spires. Renders a small cursor-anchored card with
// the tag label, region name, and (lazy-loaded) per-tag document count.
//
// Architecture: the tooltip subscribes to `hoveredHexMeta` from the knowledgeMap
// store (set by HexField on pointer-move). Cursor coordinates are updated
// imperatively via a ref-style transform — no React state on per-pixel moves,
// so the canvas-side mousemove (~300 events/s) never triggers re-renders.
//
// Visible only when the hovered hex carries a tag id; plain region terrain
// suppresses the tooltip to avoid noise (most hexes have no tag).

import { useEffect, useRef } from 'react';
import { useKnowledgeMapStore } from '../store';
import { useNotes } from '../data/useNotes';
import { resolveTagLabel } from '../util/topLevelRegions';
import type { RenderData } from '../types';

const CURSOR_OFFSET_X = 14;
const CURSOR_OFFSET_Y = 14;
const EDGE_MARGIN = 12;

export function HexTooltip({
  data,
  notesUrl,
  containerRef,
}: {
  data: RenderData;
  notesUrl: string;
  /** The DOM node whose mousemove drives the tooltip position. The R3F
   *  canvas mounts inside this element. */
  containerRef: React.RefObject<HTMLDivElement | null>;
}) {
  const meta = useKnowledgeMapStore((s) => s.hoveredHexMeta);
  const tagId = meta?.tagId ?? null;

  // Doc count comes from the same notes file the Sidebar lazy-loads.
  // Enabling on first hover preloads what the user would need on click,
  // and the fetch promise is module-cached so it never re-fires.
  const notes = useNotes(notesUrl, tagId !== null);
  const docCount =
    notes.status === 'ready' && tagId !== null
      ? (notes.byTagId.get(tagId)?.length ?? 0)
      : null;

  const tooltipRef = useRef<HTMLDivElement | null>(null);

  // Track mouse position imperatively to avoid re-rendering on every pixel.
  useEffect(() => {
    const container = containerRef.current;
    const tooltip = tooltipRef.current;
    if (!container || !tooltip) return;

    const onMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const w = tooltip.offsetWidth;
      const h = tooltip.offsetHeight;
      // Cursor-anchored, then edge-clamped inside the container.
      let x = e.clientX - rect.left + CURSOR_OFFSET_X;
      let y = e.clientY - rect.top + CURSOR_OFFSET_Y;
      if (x + w + EDGE_MARGIN > rect.width) x = e.clientX - rect.left - w - CURSOR_OFFSET_X;
      if (y + h + EDGE_MARGIN > rect.height) y = e.clientY - rect.top - h - CURSOR_OFFSET_Y;
      if (x < EDGE_MARGIN) x = EDGE_MARGIN;
      if (y < EDGE_MARGIN) y = EDGE_MARGIN;
      tooltip.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    };

    container.addEventListener('mousemove', onMove);
    return () => container.removeEventListener('mousemove', onMove);
  }, [containerRef]);

  // Suppress tooltip on non-tag hexes — most plain region terrain has no
  // tag, and a "Region: foo" tooltip on every hover would be noise.
  if (!meta || meta.tagId === null) return null;

  const region = data.regions[meta.regionIdx];
  const label = resolveTagLabel(data, meta.tagId);

  return (
    <div
      ref={tooltipRef}
      // Mouse-only affordance; the hex instances aren't keyboard-reachable
      // (InstancedMesh raycast picks). Marked aria-hidden so screen readers
      // skip it — the equivalent keyboard path is opening the
      // TagProvenanceDrawer via a CompileReport highlight chip or the
      // upcoming Documents tag typeahead. The role="tooltip" semantic would
      // conflict with aria-hidden, so it's omitted.
      aria-hidden="true"
      className="absolute top-0 left-0 pointer-events-none z-30 min-w-[160px] max-w-[280px] pt-2 px-2.5 pb-[9px] rounded-[10px] bg-[rgb(var(--c-bg)/var(--surface-overlay-alpha))] backdrop-blur-[14px] backdrop-saturate-[1.2] border border-hair shadow-[0_2px_8px_rgb(var(--c-line)/0.08)] font-sans"
      // Parked off-screen until the first mousemove positions it imperatively.
      style={{ transform: 'translate3d(-9999px, -9999px, 0)' }}
    >
      <div className="text-[13px] font-medium text-ink leading-[1.25]">
        {label}
      </div>
      <div className="mt-[3px] text-[11px] text-muted flex items-center gap-1.5">
        {region && (
          <span
            aria-hidden="true"
            // Region colour comes from the bake — stays inline.
            className="inline-block w-1.5 h-1.5 rounded-full"
            style={{ background: region.color }}
          />
        )}
        <span>{region?.name ?? 'No region'}</span>
        {docCount !== null && docCount > 0 && (
          <>
            <span aria-hidden="true">·</span>
            <span className="tabular-nums">
              {docCount} {docCount === 1 ? 'note' : 'notes'}
            </span>
          </>
        )}
      </div>
    </div>
  );
}
