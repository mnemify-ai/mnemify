// Hover preview for the region under the cursor at the current level.
//
// Hovering a region's terrain brightens its footprint at once (HexField); this
// card follows ~200 ms later with what the user would find by drilling in: the
// region's name, note count, sub-region count and a one-sentence summary. It
// is deliberately delayed so sweeping the pointer across the map doesn't rain
// cards, and it clears the moment the pointer leaves the region. It never
// navigates — clicking keeps HexField's drill-down.
//
// Same architecture as HexTooltip: subscribes to the resolved hover
// (util/hoverRegion.ts) for WHAT to show, and tracks the cursor imperatively
// for WHERE, so the ~300 mousemove/s on the canvas never re-render React.
//
// Yields to HexTooltip while the cursor sits on a tag spire — two cards
// stacked at the cursor would fight, and the tag card already names the
// region. Sidebar hover lights the terrain but shows no card: the pointer
// is over the row, not the map.

import { useEffect, useRef, useState } from 'react';
import { useKnowledgeMapStore } from '../store';
import { useMapData } from '../../app/data/MapDataProvider';
import { useHoverRegion } from '../util/hoverRegion';
import { regionTerrainFor } from '../util/regionTerrain';
import { computeSiblingInfo, regionShadeHex } from '../util/regionShade';
import type { RenderData } from '../types';

/** Delay before the preview appears once a region is hovered. */
export const PREVIEW_DELAY_MS = 200;

const CURSOR_OFFSET_X = 14;
const CURSOR_OFFSET_Y = 18;
const EDGE_MARGIN = 12;

/** First sentence of a summary, so the card stays one line of context. */
export function firstSentence(text: string | null | undefined): string | null {
  if (!text) return null;
  const trimmed = text.trim();
  if (!trimmed) return null;
  // Split on sentence-ending punctuation followed by whitespace. Abbreviations
  // ("e.g. ") are rare in these LLM summaries and cutting there is harmless.
  const m = /^(.+?[.!?])(?:\s|$)/.exec(trimmed);
  return m ? m[1] : trimmed;
}

export function RegionHoverPreview({
  data,
  containerRef,
}: {
  data: RenderData;
  /** The DOM node whose mousemove drives the card position. The R3F canvas
   *  mounts inside this element. */
  containerRef: React.RefObject<HTMLDivElement | null>;
}) {
  const hover = useHoverRegion(data);
  const hoveredTagId = useKnowledgeMapStore((s) => s.hoveredHexMeta?.tagId ?? null);
  // Optional: the sample map on the empty state has no compiled map data, so
  // counts fall back to the bake and the summary is simply omitted.
  const mapData = useMapData().data;

  // The card only ever follows a TERRAIN hover — that is where the cursor is.
  const targetIdx = hover.source === 'terrain' ? hover.idx : null;

  // Arm a timer when a region becomes hovered; disarm the instant it changes
  // or clears. `shownFor` is the region the timer fired for, so moving onto a
  // neighbouring region restarts the delay rather than swapping cards.
  const [shownFor, setShownFor] = useState<number | null>(null);
  useEffect(() => {
    if (targetIdx === null) {
      setShownFor(null);
      return;
    }
    setShownFor((cur) => (cur === targetIdx ? cur : null));
    const t = window.setTimeout(() => setShownFor(targetIdx), PREVIEW_DELAY_MS);
    return () => window.clearTimeout(t);
  }, [targetIdx]);

  const cardRef = useRef<HTMLDivElement | null>(null);

  // Track the cursor imperatively to avoid re-rendering on every pixel.
  useEffect(() => {
    const container = containerRef.current;
    const card = cardRef.current;
    if (!container || !card) return;
    const onMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const w = card.offsetWidth;
      const h = card.offsetHeight;
      let x = e.clientX - rect.left + CURSOR_OFFSET_X;
      let y = e.clientY - rect.top + CURSOR_OFFSET_Y;
      if (x + w + EDGE_MARGIN > rect.width) x = e.clientX - rect.left - w - CURSOR_OFFSET_X;
      if (y + h + EDGE_MARGIN > rect.height) y = e.clientY - rect.top - h - CURSOR_OFFSET_Y;
      if (x < EDGE_MARGIN) x = EDGE_MARGIN;
      if (y < EDGE_MARGIN) y = EDGE_MARGIN;
      card.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    };
    container.addEventListener('mousemove', onMove);
    return () => container.removeEventListener('mousemove', onMove);
    // Re-bind when the card mounts (it is conditionally rendered below).
  }, [containerRef, shownFor]);

  if (shownFor === null || shownFor !== targetIdx || hoveredTagId !== null) return null;
  const region = data.regions[shownFor];
  if (!region) return null;

  const terrain = regionTerrainFor(data);
  const subRegionCount = terrain.childrenOf(shownFor).length;
  const noteCount =
    mapData?.indexes.notesByRegionSubtree.get(region.id)?.length ?? region.notes ?? null;
  const summary = firstSentence(mapData?.attention?.regions[region.id]?.summary);
  const sib = computeSiblingInfo(data.regions);
  const swatch = regionShadeHex(region.color, sib.depth[shownFor], sib.siblingIdx[shownFor], sib.siblingCount[shownFor]);

  return (
    <div
      ref={cardRef}
      // Mouse-only affordance, like HexTooltip: the hex instances aren't
      // keyboard-reachable, and the same facts are one click away in the
      // right panel's region view.
      aria-hidden="true"
      className="absolute top-0 left-0 pointer-events-none z-30 min-w-[180px] max-w-[300px] pt-2 px-2.5 pb-[9px] rounded-[10px] bg-[rgb(var(--c-bg)/var(--surface-overlay-alpha))] backdrop-blur-[14px] backdrop-saturate-[1.2] border border-hair shadow-[0_2px_8px_rgb(var(--c-line)/0.08)] font-sans animate-fade-in motion-reduce:animate-none"
      // Parked off-screen until the first mousemove positions it imperatively.
      style={{ transform: 'translate3d(-9999px, -9999px, 0)' }}
    >
      <div className="flex items-center gap-1.5 text-[13px] font-medium text-ink leading-[1.25]">
        {/* Region colour comes from the bake — stays inline. */}
        <span aria-hidden="true" className="inline-block w-2 h-2 rounded-[2px] shrink-0" style={{ background: swatch }} />
        <span className="truncate">{region.name}</span>
      </div>
      <div className="mt-[3px] text-[11px] text-muted flex items-center gap-1.5 tabular-nums">
        {noteCount !== null && (
          <span>{noteCount} {noteCount === 1 ? 'note' : 'notes'}</span>
        )}
        {noteCount !== null && <span aria-hidden="true">·</span>}
        <span>{subRegionCount} {subRegionCount === 1 ? 'sub-region' : 'sub-regions'}</span>
      </div>
      {summary && (
        <div className="mt-1.5 text-[11.5px] leading-[1.4] text-ink/[0.72]">{summary}</div>
      )}
    </div>
  );
}
