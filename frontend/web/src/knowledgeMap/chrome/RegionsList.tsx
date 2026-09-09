// Regions index — all top-level regions, click to focus + one-shot zoom.
// The default right-panel view when nothing is focused or selected.
//
// This list is also the map's index. Hover is synced both ways: hovering (or
// tab-focusing) a row lights that region's label out on the map via
// `legendHoverIdx`, and hovering a region's terrain on the map highlights its
// row here (and scrolls it into view) via `hoveredHexMeta`.

import { useEffect, useMemo, useRef } from 'react';
import { useKnowledgeMapStore } from '../store';
import type { RenderData } from '../types';
import { buildTopLevelRegions } from '../util/topLevelRegions';
import { toRoman } from '../util/roman';
import { useTagRegionHighlight } from '../util/useTagRegionHighlight';
import { useHoverRegion } from '../util/hoverRegion';
import { kickerCls, nameEllipsisCls, rulerCls } from './panelShared';

export function RegionsList({ data }: { data: RenderData }) {
  const tops = useMemo(() => buildTopLevelRegions(data), [data]);
  const focusRegionIdx = useKnowledgeMapStore((s) => s.focusRegionIdx);
  const navigate = useKnowledgeMapStore((s) => s.navigate);
  const setLegendHover = useKnowledgeMapStore((s) => s.setLegendHover);
  // Terrain hover resolved to the top-level region (the list is only shown at
  // the map root) or the row/label under the cursor — one answer for both.
  const hover = useHoverRegion(data);
  const highlight = useTagRegionHighlight(data);

  // A row click swaps this whole list out for RegionDetail, and React fires no
  // mouseleave on unmount — without this the medallion would stay lit on a row
  // nobody is pointing at any more.
  useEffect(() => () => setLegendHover(null), [setLegendHover]);

  // Which top-level region is the current focus under?
  const activeTop = useMemo(() => {
    if (focusRegionIdx === null) return null;
    let cur = focusRegionIdx;
    while (data.regions[cur]?.parentIdx >= 0) cur = data.regions[cur].parentIdx;
    return cur;
  }, [focusRegionIdx, data.regions]);

  // Keep the terrain-hovered row in view. `nearest` only scrolls when the row
  // is actually off-screen, so sweeping the cursor across the map doesn't make
  // the list jitter. Sidebar-sourced hover is already in view by definition.
  const hoverTop = hover.source === 'terrain' ? hover.idx : null;
  const rowRefs = useRef(new Map<number, HTMLButtonElement>());
  useEffect(() => {
    if (hoverTop === null) return;
    rowRefs.current.get(hoverTop)?.scrollIntoView({ block: 'nearest' });
  }, [hoverTop]);

  if (tops.length === 0) return null;
  return (
    <section>
      <div className={kickerCls}>Regions</div>
      <div className={rulerCls} />
      <div className="flex flex-col">
        {tops.map((t) => {
          const isActive = activeTop === t.idx;
          const isHome = highlight.homeIdx === t.idx;
          const weight = highlight.related.get(t.idx);
          // Lit from the map: terrain hover, or the on-map label being hovered.
          const isMapHovered = !isActive && hover.idx === t.idx;
          return (
            <button
              key={t.region.id}
              ref={(el) => {
                if (el) rowRefs.current.set(t.idx, el);
                else rowRefs.current.delete(t.idx);
              }}
              type="button"
              // Panel click scopes + zooms the map (via the nav layer).
              onClick={() => navigate({ focusRegionIdx: t.idx, selectedTagId: null, docNoteId: null })}
              // Hover/keyboard focus reveals this region's medallion on the map.
              onMouseEnter={() => setLegendHover(t.idx)}
              onMouseLeave={() => setLegendHover(null)}
              onFocus={() => setLegendHover(t.idx)}
              onBlur={() => setLegendHover(null)}
              className={`flex items-center gap-2 w-full px-1.5 py-[5px] border-none rounded-md cursor-pointer text-left text-[13px] leading-[1.3] transition-colors duration-100 hover:bg-ink/[0.06] hover:text-ink ${
                isActive
                  ? 'bg-magenta/[0.12] text-ink'
                  : isMapHovered
                    ? 'bg-ink/[0.06] text-ink'
                    : (isHome || weight !== undefined)
                      ? 'bg-magenta/5 text-muted'
                      : 'bg-transparent text-muted'
              }`}
            >
              <span className="min-w-[30px] italic text-[12px] text-ink/70">{toRoman(t.number)}.</span>
              {/* Region colour comes from the bake — stays inline. */}
              <span className="w-[9px] h-[9px] rounded-sm shrink-0" style={{ background: t.region.color }} />
              <span className={nameEllipsisCls}>{t.region.name}</span>
              {isHome && (
                <span className="shrink-0 text-[9px] tracking-[0.08em] uppercase italic text-magenta border border-magenta/40 rounded px-1">
                  home
                </span>
              )}
              {weight !== undefined && (
                <span className="shrink-0 text-[10px] text-magenta tabular-nums">{weight.toFixed(2)}</span>
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
}
