// Shared note card — used by the right panel for both region-notes and
// tag-notes. Extracted from the old Sidebar so there's one note presentation.

import type { Note, RenderData } from '../types';

export function NoteCard({
  note,
  regions,
  onOpen,
}: {
  note: Note;
  regions: RenderData['regions'];
  /** When provided, the card becomes a button that opens the full document. */
  onOpen?: (note: Note) => void;
}) {
  const region = regions.find((r) => r.id === note.regionId);
  const dateStr = new Date(note.updatedAt).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
  return (
    <div
      className={`bg-bone/[0.55] rounded-md py-3 px-3.5 border border-hair${onOpen ? ' cursor-pointer' : ''}`}
      role={onOpen ? 'button' : undefined}
      tabIndex={onOpen ? 0 : undefined}
      onClick={onOpen ? () => onOpen(note) : undefined}
      onKeyDown={onOpen ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen(note); } } : undefined}
    >
      <div className="text-[15px] text-ink leading-[1.25]">{note.title}</div>
      <div className="text-[11px] text-muted mt-1">
        {note.author}
        {note.lastModifiedBy ? ` · edited by ${note.lastModifiedBy}` : ''} · {dateStr} ·{' '}
        <span className="uppercase tracking-[0.1em]">
          {note.source}
          {note.sourceDetail ? ` · ${note.sourceDetail}` : ''}
        </span>
      </div>
      {region && (
        <div className="text-[11px] text-ink/[0.78] mt-2 flex items-center">
          {/* Region colour comes from the bake — stays inline. */}
          <span
            className="w-2 h-2 rounded-sm inline-block mr-1.5"
            style={{ background: region.color }}
          />
          {region.name}
        </div>
      )}
      <div className="text-[13px] text-ink mt-2 leading-[1.5]">{note.excerpt}</div>
      <div className="text-[10px] text-muted/70 mt-2 text-right">{note.wordCount} words</div>
    </div>
  );
}
