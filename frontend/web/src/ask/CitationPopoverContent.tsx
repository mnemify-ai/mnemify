import { Compass, ExternalLink } from "lucide-react";
import type { ReactNode } from "react";
import type { Citation } from "./types";
import {
  formatShortDate,
  layerName,
  terrainFocusTarget,
  type TerrainFocusTarget,
} from "./citationDisplay";
import type { SourceInspectorTarget } from "./SourceInspector";

/**
 * Shared popover body for "why does Mnemify believe this?" — one row per
 * citation, reused by a single citation chip's popover and the grouped
 * "N sources" inline control. Every citation gets a "Show on map" action
 * when it (or its home region) has a map location; citations backed by an
 * expanded document passage also get "View source" per passage.
 */
export function CitationPopoverContent({
  citations,
  onFocusTerrain,
  onViewSource,
}: {
  citations: Citation[];
  onFocusTerrain?: (target: TerrainFocusTarget) => void;
  onViewSource?: (target: SourceInspectorTarget) => void;
}) {
  return (
    <div className="max-w-xs divide-y divide-hair">
      {citations.map((c) => (
        <div key={c.citation_id} className="py-2 first:pt-0 last:pb-0">
          <CitationRow
            citation={c}
            onFocusTerrain={onFocusTerrain}
            onViewSource={onViewSource}
          />
        </div>
      ))}
    </div>
  );
}

function CitationRow({
  citation: c,
  onFocusTerrain,
  onViewSource,
}: {
  citation: Citation;
  onFocusTerrain?: (target: TerrainFocusTarget) => void;
  onViewSource?: (target: SourceInspectorTarget) => void;
}) {
  const refs = c.source_refs || [];
  const focus = terrainFocusTarget(c);

  const eyebrow = c.edge_provenance
    ? `${layerName(c.layer)} · ${c.edge_provenance}`
    : layerName(c.layer);

  return (
    <div className="space-y-2">
      <div className="font-sans text-[10px] uppercase tracking-wide text-muted">
        {eyebrow}
      </div>

      {refs.length === 0 ? (
        <div className="font-sans text-[12px] font-medium text-ink">{c.label}</div>
      ) : (
        refs.map((r, i) => (
          <div key={i} className="space-y-1">
            <div className="font-sans text-[12px] font-medium text-ink">{r.doc_title}</div>
            {r.heading ? (
              <div className="font-sans text-[10px] text-muted">{r.heading}</div>
            ) : null}
            <p className="font-sans text-[11px] leading-relaxed text-ink/80 line-clamp-3">
              {r.excerpt}
            </p>
            <div className="flex items-center justify-between gap-2">
              <span className="font-sans text-[10px] text-muted">
                {formatShortDate(r.updated_at)}
              </span>
              <div className="flex items-center gap-2">
                {r.doc_id && onViewSource ? (
                  <ActionButton
                    onClick={() =>
                      onViewSource({
                        docId: r.doc_id!,
                        heading: r.heading,
                        excerpt: r.excerpt,
                        updatedAt: r.updated_at,
                        sourceUrl: r.source_url,
                        terrainFocus: focus,
                      })
                    }
                  >
                    View source
                  </ActionButton>
                ) : r.source_url ? (
                  <a
                    href={r.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 font-sans text-[10px] text-magenta hover:underline"
                  >
                    Open source
                    <ExternalLink size={10} strokeWidth={1.5} aria-hidden />
                  </a>
                ) : null}
              </div>
            </div>
          </div>
        ))
      )}

      {focus && onFocusTerrain ? (
        <ActionButton icon={<Compass size={11} strokeWidth={1.5} aria-hidden />} onClick={() => onFocusTerrain(focus)}>
          Show on map
        </ActionButton>
      ) : null}
    </div>
  );
}

function ActionButton({
  onClick,
  icon,
  children,
}: {
  onClick: () => void;
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 font-sans text-[10px] text-magenta hover:underline"
    >
      {icon}
      {children}
    </button>
  );
}
