// Region detail view: nav header + overview + Topics / Highlights / Docs tabs
// for the currently focused region (drill depth).

import { useEffect, useMemo, useRef, useState } from 'react';
import { useKnowledgeMapStore } from '../store';
import type { RenderData } from '../types';
import { buildTopLevelRegions, resolveTagLabel } from '../util/topLevelRegions';
import { toRoman } from '../util/roman';
import { computeSiblingInfo, regionShadeHex } from '../util/regionShade';
import { useMapDataReady } from '../../app/data/MapDataProvider';
import { useHoverRegion } from '../util/hoverRegion';
import { NoteCard } from './NoteCard';
import { SignalGroups } from './SignalGroups';
import {
  AttentionGauge, BackBar, Stat, TabBar, levelColor,
  MAX_NOTES, MAX_TAGS,
  bodyCls, chipCls, chipBaseCls, chipWrapCls, emptyCls, headerCls, kickerCls,
  notesWrapCls, rulerCls, subKickerCls, summaryCls, titleCls,
} from './panelShared';

type DetailTab = 'topics' | 'signals' | 'docs';

export function RegionDetail({ data, idx }: { data: RenderData; idx: number }) {
  const { indexes, attention, notes } = useMapDataReady();
  const navigate = useKnowledgeMapStore((s) => s.navigate);
  const setLegendHover = useKnowledgeMapStore((s) => s.setLegendHover);
  // Hover is synced both ways with the map: the sub-region under the cursor on
  // the terrain lights its row here, and hovering a row lights its terrain
  // footprint + on-map label (see util/hoverRegion.ts). Hover never navigates.
  const hover = useHoverRegion(data);
  const region = data.regions[idx];

  // Drilling into a sub-region swaps this view out, and React fires no
  // mouseleave on unmount — clear so the terrain doesn't stay lit for a row
  // nobody is pointing at any more.
  useEffect(() => () => setLegendHover(null), [setLegendHover]);

  // Keep the terrain-hovered sub-region row in view; `nearest` only scrolls
  // when it is actually off-screen so sweeping the map doesn't jitter the list.
  const rowRefs = useRef(new Map<number, HTMLButtonElement>());
  const terrainHoverIdx = hover.source === 'terrain' ? hover.idx : null;
  useEffect(() => {
    if (terrainHoverIdx === null) return;
    rowRefs.current.get(terrainHoverIdx)?.scrollIntoView({ block: 'nearest' });
  }, [terrainHoverIdx]);
  const attentionItem = region ? attention?.regions[region.id] ?? null : null;
  const roman = useRomanForRegion(data, idx);
  const notesById = useMemo(
    () => new Map(notes.notes.map((n) => [n.id, n])),
    [notes.notes],
  );

  const subRegions = useMemo(() => {
    const sib = computeSiblingInfo(data.regions);
    return data.regions
      .map((r, i) => ({ r, i }))
      .filter(({ r }) => r.parentIdx === idx)
      .map(({ r, i }) => {
        const a = attention?.regions[r.id];
        return {
          idx: i,
          name: r.name,
          color: regionShadeHex(r.color, sib.depth[i], sib.siblingIdx[i], sib.siblingCount[i]),
          summary: a?.summary ?? '',
          level: a?.attentionLevel ?? 'none',
        };
      });
  }, [data.regions, idx, attention]);
  const tagsInside = useMemo(() => {
    const focusedId = region?.id;
    if (!focusedId) return [] as { id: string; label: string }[];
    const out: { id: string; label: string }[] = [];
    for (const tagId of data.tagIndex) {
      const leaf = indexes.regionByTagId.get(tagId);
      if (leaf && isDescendantOrSelf(data, leaf.id, focusedId)) {
        out.push({ id: tagId, label: resolveTagLabel(data, tagId) });
      }
    }
    return out;
  }, [data, idx, indexes, region?.id]);
  const notesInside = useMemo(
    () => (region ? indexes.notesByRegionSubtree.get(region.id) ?? [] : []),
    [indexes, region],
  );
  const signals = attentionItem?.signals ?? [];

  // A leaf region has nothing left to drill into, so Topics opens on a dead
  // end ("No topics in this region.") right when the user has finished
  // exploring. At a leaf the documents *are* the content, so land on Docs —
  // unless there are none, in which case Topics may still hold tags.
  const defaultTab: DetailTab =
    subRegions.length === 0 && notesInside.length > 0 ? 'docs' : 'topics';
  const [tab, setTab] = useState<DetailTab>(defaultTab);
  // This component stays mounted across drill navigation, so the tab has to be
  // re-defaulted per region. Keyed on the region id rather than run on every
  // render: a tab the user picked by hand sticks while they stay put.
  const tabRegionRef = useRef(region?.id);
  useEffect(() => {
    if (tabRegionRef.current === region?.id) return;
    tabRegionRef.current = region?.id;
    setTab(defaultTab);
  }, [region?.id, defaultTab]);

  if (!region) return null;

  return (
    <>
      <BackBar data={data} regionIdx={idx} />
      <div className={headerCls}>
        <div className={kickerCls}>Region</div>
        <div className={rulerCls} />
        <div className="flex items-center gap-2 mb-2.5">
          {roman !== null && (
            <span className="shrink-0 min-w-[22px] h-[22px] px-[5px] rounded-full inline-grid place-items-center border border-line/[0.35] bg-cream/60 italic text-[11px] font-semibold text-ink">
              {toRoman(roman)}
            </span>
          )}
          {/* Region colour comes from the bake — stays inline. */}
          <span className="w-3 h-3 rounded-[3px] shrink-0" style={{ background: region.color }} />
          <span className={titleCls}>{region.name}</span>
        </div>
        <div className="grid grid-cols-2 gap-2.5">
          <Stat label="Notes" value={region.notes} />
          <Stat label="Sources" value={region.sources} />
          <Stat label="Tags" value={region.tagCount} />
          <Stat label="Sub-regions" value={subRegions.length} />
        </div>
        {attentionItem && attentionItem.attentionScore > 0 && (
          <AttentionGauge score={attentionItem.attentionScore} level={attentionItem.attentionLevel} />
        )}
        {attentionItem?.summary && <div className={summaryCls}>{attentionItem.summary}</div>}
      </div>

      <TabBar
        active={tab}
        onChange={(k) => setTab(k as DetailTab)}
        tabs={[
          { key: 'topics', label: 'Topics', count: subRegions.length + tagsInside.length },
          { key: 'signals', label: 'Highlights', count: signals.length },
          { key: 'docs', label: 'Docs', count: notesInside.length },
        ]}
      />

      <div className={bodyCls}>
        {tab === 'topics' && (
          <>
            {subRegions.length > 0 && (
              <div>
                <div className={subKickerCls}>Sub-regions</div>
                <div className="flex flex-col gap-0.5">
                  {subRegions.map((s) => (
                    <button
                      key={s.idx}
                      ref={(el) => {
                        if (el) rowRefs.current.set(s.idx, el);
                        else rowRefs.current.delete(s.idx);
                      }}
                      type="button"
                      className={`flex items-start gap-[9px] w-full px-1.5 py-2 border-none rounded-md cursor-pointer text-left transition-colors duration-100 hover:bg-ink/[0.06] ${
                        hover.idx === s.idx ? 'bg-ink/[0.06]' : 'bg-transparent'
                      }`}
                      onClick={() => navigate({ focusRegionIdx: s.idx, selectedTagId: null, docNoteId: null })}
                      onMouseEnter={() => setLegendHover(s.idx)}
                      onMouseLeave={() => setLegendHover(null)}
                      onFocus={() => setLegendHover(s.idx)}
                      onBlur={() => setLegendHover(null)}
                    >
                      {/* Sibling-shaded region colour — stays inline. */}
                      <span className="w-2.5 h-2.5 rounded-[3px] shrink-0 mt-[3px]" style={{ background: s.color }} />
                      <span className="flex-1 min-w-0">
                        <span className="block text-[14px] font-semibold text-ink leading-[1.25]">{s.name}</span>
                        {s.summary && (
                          <span className="line-clamp-2 mt-0.5 text-[11.5px] leading-[1.4] text-ink/[0.62]">
                            {s.summary}
                          </span>
                        )}
                      </span>
                      {s.level !== 'none' && (
                        <span
                          title={`Attention: ${s.level}`}
                          // Dot colour is attention-level-derived — stays inline.
                          className="w-[7px] h-[7px] rounded-full shrink-0 mt-[5px]"
                          style={{ background: levelColor(s.level) }}
                        />
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {tagsInside.length > 0 && (
              <div className={subRegions.length > 0 ? 'mt-3.5' : undefined}>
                <div className={subKickerCls}>Tags</div>
                <div className={chipWrapCls}>
                  {tagsInside.slice(0, MAX_TAGS).map((t) => (
                    <button key={t.id} type="button" className={chipCls} onClick={() => navigate({ selectedTagId: t.id })}>
                      {t.label}
                    </button>
                  ))}
                  {tagsInside.length > MAX_TAGS && (
                    <span className={`${chipBaseCls} cursor-default`}>+{tagsInside.length - MAX_TAGS}</span>
                  )}
                </div>
              </div>
            )}
            {subRegions.length === 0 && tagsInside.length === 0 && (
              <div className={emptyCls}>No topics in this region.</div>
            )}
          </>
        )}

        {tab === 'signals' && (
          signals.length > 0
            ? <SignalGroups signals={signals} notesById={notesById} />
            : <div className={emptyCls}>No open risks, decisions, or questions.</div>
        )}

        {tab === 'docs' && (
          notesInside.length > 0
            ? (
              <div className={notesWrapCls}>
                {notesInside.slice(0, MAX_NOTES).map((n) => (
                  <NoteCard key={n.id} note={n} regions={data.regions} onOpen={(note) => navigate({ docNoteId: note.id })} />
                ))}
                {notesInside.length > MAX_NOTES && (
                  <div className={emptyCls}>+{notesInside.length - MAX_NOTES} more</div>
                )}
              </div>
            )
            : <div className={emptyCls}>No active documents.</div>
        )}
      </div>
    </>
  );
}

/** Roman numeral (1-based) of the top-level region containing `idx`, or null. */
function useRomanForRegion(data: RenderData, idx: number): number | null {
  return useMemo(() => {
    const tops = buildTopLevelRegions(data);
    let cur = idx;
    while (data.regions[cur]?.parentIdx >= 0) cur = data.regions[cur].parentIdx;
    return tops.find((t) => t.idx === cur)?.number ?? null;
  }, [data, idx]);
}

function isDescendantOrSelf(data: RenderData, leafRegionId: string, focusedId: string): boolean {
  let cur = data.regions.findIndex((r) => r.id === leafRegionId);
  while (cur >= 0) {
    if (data.regions[cur].id === focusedId) return true;
    cur = data.regions[cur].parentIdx;
  }
  return false;
}
