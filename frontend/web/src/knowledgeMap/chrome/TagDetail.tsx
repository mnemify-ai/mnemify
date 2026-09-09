// Tag detail view: pinned overview + Related / Highlights / Docs tabs for the
// currently selected tag.

import { useMemo, useState } from 'react';
import { useKnowledgeMapStore } from '../store';
import type { RenderData } from '../types';
import { resolveTagLabel } from '../util/topLevelRegions';
import { useTagRegionHighlight } from '../util/useTagRegionHighlight';
import { useMapDataReady } from '../../app/data/MapDataProvider';
import { useTagInfo, useNotesForTag, tagIdToLabel } from '../../app/data/selectors';
import { NoteCard } from './NoteCard';
import { SignalGroups } from './SignalGroups';
import {
  AttentionGauge, BackBar, TabBar, MAX_NOTES,
  bodyCls, chipCls, chipWrapCls, emptyCls, headerCls, kickerCls,
  nameEllipsisCls, notesWrapCls, pathCls, rulerCls, subKickerCls, summaryCls, titleCls,
} from './panelShared';

export function TagDetail({ data, tagId }: { data: RenderData; tagId: string }) {
  const info = useTagInfo(tagId);
  const notes = useNotesForTag(tagId);
  const mapData = useMapDataReady();
  const navigate = useKnowledgeMapStore((s) => s.navigate);
  const focusRegionIdx = useKnowledgeMapStore((s) => s.focusRegionIdx);
  const highlight = useTagRegionHighlight(data);
  const attentionItem = mapData.attention?.tags[tagId] ?? null;
  const notesById = useMemo(
    () => new Map(mapData.notes.notes.map((n) => [n.id, n])),
    [mapData.notes.notes],
  );

  const alsoResembles = useMemo(
    () => [...highlight.related.entries()].map(([regionIdx, weight]) => ({
      regionIdx, region: data.regions[regionIdx], weight,
    })).filter((x) => x.region),
    [highlight, data.regions],
  );

  // A tag can exist in notes/attention but not on the hex map (the bake drops
  // some tags), so `info` may be null — the attention label is still the real
  // LLM name, unlike the id-derived fallback ("Node Cca56d5da8e173e8").
  const label = info?.label ?? attentionItem?.label ?? tagIdToLabel(tagId);
  const relatedTagIds = info?.relatedTagIds ?? [];
  const signals = attentionItem?.signals ?? [];
  const [tab, setTab] = useState<'related' | 'signals' | 'docs'>('related');

  return (
    <>
      <BackBar data={data} regionIdx={focusRegionIdx} />
      <div className={headerCls}>
        <div className={kickerCls}>Tag</div>
        <div className={rulerCls} />
        <div className={titleCls}>{label}</div>
        {info?.topRegion && (
          <div className={`${pathCls} mt-1`}>in {info.topRegion.name}</div>
        )}
        {attentionItem && attentionItem.attentionScore > 0 && (
          <AttentionGauge score={attentionItem.attentionScore} level={attentionItem.attentionLevel} />
        )}
        {attentionItem?.summary && <div className={summaryCls}>{attentionItem.summary}</div>}
      </div>

      <TabBar
        active={tab}
        onChange={(k) => setTab(k as typeof tab)}
        tabs={[
          { key: 'related', label: 'Related', count: alsoResembles.length + relatedTagIds.length },
          { key: 'signals', label: 'Highlights', count: signals.length },
          { key: 'docs', label: 'Docs', count: notes.length },
        ]}
      />

      <div className={bodyCls}>
        {tab === 'related' && (
          <>
            {alsoResembles.length > 0 && (
              <div>
                <div className={subKickerCls}>Also resembles</div>
                <div className="flex flex-col gap-1 mt-1.5">
                  {alsoResembles.map(({ regionIdx, region, weight }) => (
                    <button
                      key={region.id}
                      type="button"
                      className="flex items-center gap-1.5 text-[12px] text-ink/[0.85] border-none bg-transparent cursor-pointer w-full text-left py-0.5"
                      onClick={() => navigate({ focusRegionIdx: regionIdx, selectedTagId: null, docNoteId: null })}
                    >
                      {/* Region colour comes from the bake — stays inline. */}
                      <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: region.color }} />
                      <span className={nameEllipsisCls}>{region.name}</span>
                      <span className="w-11 h-1 rounded-sm bg-line/25 shrink-0 overflow-hidden">
                        {/* Width + colour are data-driven — stays inline. */}
                        <span
                          className="block h-full rounded-sm"
                          style={{ width: `${Math.round(Math.min(1, Math.max(0, weight)) * 100)}%`, background: region.color }}
                        />
                      </span>
                      <span className="w-[26px] text-right text-[10px] tabular-nums text-muted shrink-0">
                        {weight.toFixed(2)}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            {relatedTagIds.length > 0 && (
              <div className={alsoResembles.length > 0 ? 'mt-3.5' : undefined}>
                <div className={subKickerCls}>Related tags</div>
                <div className={chipWrapCls}>
                  {relatedTagIds.slice(0, 12).map((id) => (
                    <button key={id} type="button" className={chipCls} onClick={() => navigate({ selectedTagId: id })}>
                      {resolveTagLabel(data, id)}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {alsoResembles.length === 0 && relatedTagIds.length === 0 && (
              <div className={emptyCls}>No related regions or tags.</div>
            )}
          </>
        )}

        {tab === 'signals' && (
          signals.length > 0
            ? <SignalGroups signals={signals} notesById={notesById} />
            : <div className={emptyCls}>No open risks, decisions, or questions.</div>
        )}

        {tab === 'docs' && (
          notes.length > 0
            ? (
              <div className={notesWrapCls}>
                {notes.slice(0, MAX_NOTES).map((n) => (
                  <NoteCard key={n.id} note={n} regions={data.regions} onOpen={(note) => navigate({ docNoteId: note.id })} />
                ))}
                {notes.length > MAX_NOTES && (
                  <div className={emptyCls}>+{notes.length - MAX_NOTES} more</div>
                )}
              </div>
            )
            : <div className={emptyCls}>No documents for this tag.</div>
        )}
      </div>
    </>
  );
}
