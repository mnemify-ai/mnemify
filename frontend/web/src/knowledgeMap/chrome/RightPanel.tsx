// Unified right panel: a single scrolling column that replaces the old
// RegionPanel + RegionLegend + Sidebar + TagProvenanceDrawer + Sources card.
//
// Top → bottom:
//   1. REGIONS — all top-level regions, click to focus + one-shot zoom.
//   2. REGION detail for the current focus (drill depth): stats, tags inside,
//      notes inside.
//   3. TAG detail when a tag is selected: "also resembles" region weights,
//      related tags, contributing notes.
//
// Lives inside <KnowledgeMap> so it has the knowledgeMap store (focus/selectedTag) AND
// is under the app-root MapDataProvider (useTagInfo/useNotesForTag/indexes).
//
// This file is just the router; the views live in RegionsList / RegionDetail /
// TagDetail / DocDetail, with shared chrome in panelShared.

import { useKnowledgeMapStore } from '../store';
import type { RenderData } from '../types';
import { panelFontCls } from './panelShared';
import { RegionsList } from './RegionsList';
import { RegionDetail } from './RegionDetail';
import { TagDetail } from './TagDetail';
import { DocDetail } from './DocDetail';

// Tabbed views: header + tab bar pinned, only the body scrolls.
const tabShellCls = `flex flex-col h-full min-h-0 overflow-hidden ${panelFontCls}`;

export function RightPanel({ data }: { data: RenderData }) {
  const focusRegionIdx = useKnowledgeMapStore((s) => s.focusRegionIdx);
  const selectedTagId = useKnowledgeMapStore((s) => s.selectedTagId);
  const docNoteId = useKnowledgeMapStore((s) => s.docNoteId);

  // The panel body is a single navigable stack driven by committed clicks (not
  // hover — hover is surfaced by the cursor tooltip). Precedence top→bottom:
  //   • an open document  → DocDetail
  //   • a selected tag    → TagDetail
  //   • a focused region  → RegionDetail
  //   • none              → the Regions index
  if (docNoteId) {
    return <div className={tabShellCls}><DocDetail key={docNoteId} data={data} noteId={docNoteId} /></div>;
  }
  if (selectedTagId) {
    return <div className={tabShellCls}><TagDetail key={selectedTagId} data={data} tagId={selectedTagId} /></div>;
  }
  if (focusRegionIdx !== null) {
    return <div className={tabShellCls}><RegionDetail key={focusRegionIdx} data={data} idx={focusRegionIdx} /></div>;
  }
  return (
    <div className={`flex flex-col gap-[18px] h-full min-h-0 overflow-auto ${panelFontCls}`}>
      <RegionsList data={data} />
    </div>
  );
}
