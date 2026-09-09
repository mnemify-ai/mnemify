// Doc view: the real Documents-tab viewer, embedded in the panel, with a
// note-level fallback when the note has no matching document in the DB.

import { useMemo } from 'react';
import { ExternalLink } from 'lucide-react';
import { useKnowledgeMapStore } from '../store';
import type { Note, RenderData } from '../types';
import { useDocIdForNote } from '../util/useDocResolver';
import { useMapDataReady } from '../../app/data/MapDataProvider';
import { DocViewerPane } from '../../app/components/DocViewerPane';
import {
  BackBar, emptyBaseCls, kickerCls, pathCls, rulerCls, summaryCls, titleCls,
} from './panelShared';

export function DocDetail({ data, noteId }: { data: RenderData; noteId: string }) {
  const back = useKnowledgeMapStore((s) => s.back);
  const focusRegionIdx = useKnowledgeMapStore((s) => s.focusRegionIdx);
  const { notes } = useMapDataReady();
  const note = useMemo(() => notes.notes.find((n) => n.id === noteId) ?? null, [notes.notes, noteId]);
  const { docId, loading } = useDocIdForNote(note);

  return (
    <>
      <BackBar data={data} regionIdx={focusRegionIdx} />
      <div className="flex-1 min-h-0 flex flex-col">
        {docId ? (
          <DocViewerPane docId={docId} onClose={back} />
        ) : loading ? (
          <div className={`${emptyBaseCls} p-4`}>Loading document…</div>
        ) : note ? (
          <NoteDetail note={note} data={data} />
        ) : (
          <div className={`${emptyBaseCls} p-4`}>Document not found.</div>
        )}
      </div>
    </>
  );
}

// Fallback when a note has no matching document in the Documents DB: show what
// the note itself carries (title, source, excerpt) + a link out to the source.
function NoteDetail({ note, data }: { note: Note; data: RenderData }) {
  const region = data.regions.find((r) => r.id === note.regionId);
  const date = new Date(note.updatedAt).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
  return (
    <div className="flex-1 min-h-0 overflow-auto py-1 px-0.5">
      <div className={kickerCls}>Document</div>
      <div className={rulerCls} />
      <div className={titleCls}>{note.title}</div>
      <div className={`${pathCls} mt-1.5`}>
        {note.author} · {date} ·{' '}
        <span className="uppercase tracking-[0.1em]">
          {note.source}
          {note.sourceDetail ? ` · ${note.sourceDetail}` : ''}
        </span>
      </div>
      {region && (
        <div className={`${pathCls} flex items-center gap-1.5 mt-0.5`}>
          {/* Region colour comes from the bake — stays inline. */}
          <span className="w-2 h-2 rounded-sm" style={{ background: region.color }} />
          {region.name}
        </div>
      )}
      <div className={summaryCls}>{note.excerpt}</div>
      {note.sourceUrl && (
        <a
          href={note.sourceUrl}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 mt-3.5 text-[12px] text-magenta no-underline"
        >
          <ExternalLink size={13} /> Open in {note.source}
        </a>
      )}
    </div>
  );
}
