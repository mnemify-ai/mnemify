import { Activity, BadgeCheck, FileText, Mountain, Shapes, Tag } from "lucide-react";
import { cn } from "../app/lib/cn";
import { formatRelativeDate, layerName, NODE_TYPE_META } from "./citationDisplay";
import type { Citation } from "./types";

/** Tiny per-node-type glyph so chip tinting isn't the only type signal
 *  (color-blind safe). Shapes are distinct even when the color class is
 *  muted; always `aria-hidden` — the accessible name lives on the chip. */
const GLYPH_BY_TYPE: Record<Citation["node_type"], typeof Mountain> = {
  region: Mountain,
  tag: Tag,
  note: FileText,
  entity: Shapes,
  signal: Activity,
};

export function NodeTypeGlyph({
  type,
  className,
  size = 10,
}: {
  type: Citation["node_type"];
  className?: string;
  size?: number;
}) {
  const Icon = GLYPH_BY_TYPE[type];
  return (
    <Icon
      size={size}
      strokeWidth={1.75}
      aria-hidden
      className={cn("shrink-0", className)}
    />
  );
}

/**
 * Hover/focus preview card for a citation chip — the "read the evidence
 * without committing" surface. Leads with the server-verified excerpt (the
 * quote backing the claim, our differentiator) as a left-accent quote block;
 * click on the chip remains the action surface (CitationPopoverContent).
 */
export function CitationHoverPreview({ citation }: { citation: Citation }) {
  const meta = NODE_TYPE_META[citation.node_type];
  const primary = citation.source_refs?.[0];
  const extra = (citation.source_refs?.length ?? 0) - 1;
  const updated = formatRelativeDate(primary?.updated_at);

  return (
    <div className="w-64 space-y-1.5">
      {/* Node label + type eyebrow */}
      <div className="flex items-center gap-1.5 font-sans text-[10px] uppercase tracking-wide text-muted">
        <NodeTypeGlyph type={citation.node_type} className={meta.glyph} />
        <span>{meta.display}</span>
        <span aria-hidden>·</span>
        <span className="min-w-0 truncate normal-case tracking-normal text-ink/80">
          {citation.label}
        </span>
      </div>

      {primary ? (
        <>
          <div className="font-sans text-[12px] font-medium leading-snug text-ink">
            {primary.doc_title}
          </div>
          {primary.heading ? (
            <div className="font-sans text-[10px] text-muted">{primary.heading}</div>
          ) : null}

          {/* The verified quote — server-checked evidence, kept prominent. */}
          <figure className="rounded-r-md border-l-2 border-magenta/60 bg-bone/60 px-2.5 py-1.5">
            <figcaption className="mb-1 flex items-center gap-1 font-sans text-[9px] font-medium uppercase tracking-wide text-muted">
              <BadgeCheck size={10} strokeWidth={1.75} aria-hidden className="text-success" />
              Verified quote
            </figcaption>
            <blockquote className="font-serif text-[12px] italic leading-relaxed text-ink line-clamp-4">
              {primary.excerpt}
            </blockquote>
          </figure>

          {updated || extra > 0 ? (
            <div className="flex items-center justify-between gap-2 font-sans text-[10px] text-muted">
              <span>{updated ? `Updated ${updated}` : ""}</span>
              {extra > 0 ? (
                <span>
                  +{extra} more passage{extra > 1 ? "s" : ""}
                </span>
              ) : null}
            </div>
          ) : null}
        </>
      ) : (
        // tag/entity/region citations carry no expanded passages — show what
        // the graph knows instead of an empty card.
        <div className="font-sans text-[11px] leading-relaxed text-ink/80">
          Cited from the {layerName(citation.layer)} layer of your knowledge map
          {citation.edge_provenance ? ` (${citation.edge_provenance})` : ""}.
        </div>
      )}

      <div className="border-t border-hair pt-1 font-sans text-[9px] text-muted">
        Click for source actions
      </div>
    </div>
  );
}
