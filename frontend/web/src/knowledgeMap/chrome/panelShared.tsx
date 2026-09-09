// Shared bits for the right-panel views: the panel typography/spacing class
// strings, the Back + breadcrumb nav header, the tab bar, the attention gauge,
// and small helpers. Split out of the old monolithic RightPanel.tsx.

import { useMemo } from 'react';
import { ChevronLeft } from 'lucide-react';
import { useKnowledgeMapStore } from '../store';
import type { RenderData } from '../types';

export const MAX_NOTES = 30;
export const MAX_TAGS = 40;

// The panel speaks the app serif; ui-serif first so Safari renders New York.
export const panelFontCls =
  "font-[ui-serif,'Newsreader',Georgia,'Times_New_Roman',serif]";

// ── shared class strings ─────────────────────────────────────────────────────
export const kickerCls =
  'text-[11px] tracking-eyebrow uppercase text-muted italic font-medium';
export const subKickerCls =
  'text-[10px] tracking-[0.14em] uppercase text-muted font-medium mb-1';
export const rulerCls = 'h-px bg-line/[0.22] mt-1.5 mb-2';
// Base without padding so callers can swap the padding without a class-order
// fight (Tailwind resolves py-1 vs py-0.5 by stylesheet order, not className).
export const emptyBaseCls = 'text-[12px] text-muted italic';
export const emptyCls = `${emptyBaseCls} py-1`;
export const headerCls = 'flex-none pb-3';
export const bodyCls = 'flex-1 min-h-0 overflow-auto pt-1';
export const titleCls = 'text-[17px] font-semibold text-ink leading-[1.2]';
export const pathCls = 'text-[11px] text-muted mb-1.5';
export const summaryCls = 'mt-2.5 text-[12.5px] leading-[1.45] text-ink/[0.78]';
export const nameEllipsisCls = 'flex-1 truncate text-[13px]';
export const chipWrapCls = 'flex flex-wrap gap-1.5';
export const chipBaseCls =
  'text-[12px] px-2 py-[3px] rounded-full border border-line/25 ' +
  'bg-bone/40 text-ink/[0.85] max-w-full truncate';
export const chipCls = `${chipBaseCls} cursor-pointer`;
export const notesWrapCls = 'flex flex-col gap-2';

// Attention level → colour, shared by the gauge and sub-region dots. Matches
// the Highlights severity pills / burning overlay so the whole panel speaks
// one palette. Raw hexes are intentional — these are data-severity accents,
// not theme surfaces.
export function levelColor(level?: string): string {
  return level === 'critical' ? '#E11D48'
    : level === 'high' ? '#F97316'
      : level === 'medium' ? '#F59E0B'
        : level === 'low' ? '#14B8A6'
          : '#9AA0A6';
}

// ── Nav header: Back + clickable breadcrumb path. Shared by every detail view.
// Replaces the old on-map Breadcrumb so map↔panel navigation lives in one place.
export function BackBar({ data, regionIdx }: { data: RenderData; regionIdx: number | null }) {
  const back = useKnowledgeMapStore((s) => s.back);
  const navigate = useKnowledgeMapStore((s) => s.navigate);
  const canGoBack = useKnowledgeMapStore((s) => s.navHistory.length > 0);
  const path = useMemo(() => (regionIdx === null ? [] : walkAncestors(data, regionIdx)), [data, regionIdx]);
  const idxOf = useMemo(() => {
    const m = new Map<string, number>();
    data.regions.forEach((r, i) => m.set(r.id, i));
    return m;
  }, [data.regions]);

  return (
    <div className="flex-none flex items-center gap-2.5 pb-2 flex-wrap">
      <button
        type="button"
        className="inline-flex items-center gap-0.5 border border-line/25 rounded-md bg-bone/40 text-ink/[0.85] text-[12px] py-[3px] pr-2 pl-[5px] cursor-pointer disabled:opacity-40 disabled:cursor-default"
        onClick={() => canGoBack && back()}
        disabled={!canGoBack}
      >
        <ChevronLeft size={14} strokeWidth={2.5} /> Back
      </button>
      <div className="flex items-center gap-1 flex-wrap text-[11px] text-muted min-w-0">
        <button type="button" className={crumbCls} onClick={() => navigate({ focusRegionIdx: null, selectedTagId: null, docNoteId: null })}>Map</button>
        {path.map((r) => (
          <span key={r.id} className="contents">
            <span className="text-muted/60">›</span>
            <button
              type="button"
              className={crumbCls}
              onClick={() => navigate({ focusRegionIdx: idxOf.get(r.id) ?? null, selectedTagId: null, docNoteId: null })}
            >
              {r.name}
            </button>
          </span>
        ))}
      </div>
    </div>
  );
}

const crumbCls =
  'border-none bg-transparent cursor-pointer text-muted text-[11px] p-0 max-w-[120px] truncate';

function walkAncestors(data: RenderData, idx: number): RenderData['regions'] {
  const chain: RenderData['regions'] = [];
  let cur = idx;
  while (cur >= 0) {
    const region = data.regions[cur];
    if (!region) break;
    chain.unshift(region);
    cur = region.parentIdx;
  }
  return chain;
}

// ── Tab bar ──────────────────────────────────────────────────────────────────
type TabKey = string;
export function TabBar({
  tabs,
  active,
  onChange,
}: {
  tabs: { key: TabKey; label: string; count?: number }[];
  active: TabKey;
  onChange: (k: TabKey) => void;
}) {
  return (
    <div
      className="grid gap-1 p-[3px] mb-2 border border-line/25 rounded-md bg-bone/[0.32]"
      // Column count follows the tab list — genuinely dynamic.
      style={{ gridTemplateColumns: `repeat(${tabs.length}, 1fr)` }}
    >
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          className={`border-none rounded px-1.5 py-[5px] text-[12px] cursor-pointer ${
            active === t.key ? 'text-ink bg-magenta/[0.14]' : 'text-muted bg-transparent'
          }`}
          onClick={() => onChange(t.key)}
        >
          {t.label}
          {t.count !== undefined && t.count > 0 && (
            <span className="ml-[5px] text-[10px] tabular-nums opacity-70">{t.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

// A labelled attention meter — replaces the cryptic "Medium 37" badge.
export function AttentionGauge({ score, level }: { score: number; level: string }) {
  const color = levelColor(level);
  const pct = Math.max(0, Math.min(100, Math.round(score)));
  return (
    <div className="mt-3" title="Attention — surfaced from open risks, decisions & questions in this area">
      <div className="flex items-baseline justify-between mb-[5px]">
        <span className="text-[10px] tracking-[0.14em] uppercase text-muted font-medium">Attention</span>
        {/* Colour is level-derived — stays inline. */}
        <span className="font-semibold capitalize text-[12px]" style={{ color }}>
          {level}
        </span>
      </div>
      <div className="h-1.5 rounded-[3px] bg-line/[0.22] overflow-hidden">
        <span className="block h-full rounded-[3px]" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

export function Stat({ label, value }: { label: string; value: number | undefined }) {
  if (value === undefined) return null;
  return (
    <div>
      <div className="text-[18px] font-semibold text-ink tabular-nums">{value}</div>
      <div className="text-[10px] tracking-[0.06em] uppercase text-muted">{label}</div>
    </div>
  );
}
