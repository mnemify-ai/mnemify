import * as RadixPopover from "@radix-ui/react-popover";
import * as RadixTooltip from "@radix-ui/react-tooltip";
import { useState } from "react";
import { cn } from "../app/lib/cn";
import { CitationHoverPreview, NodeTypeGlyph } from "./CitationHoverPreview";
import { CitationPopoverContent } from "./CitationPopoverContent";
import {
  NODE_TYPE_META,
  provenanceClass,
  type TerrainFocusTarget,
} from "./citationDisplay";
import type { SourceInspectorTarget } from "./SourceInspector";
import type { Citation } from "./types";

/**
 * One citation chip. Hover (or keyboard focus) shows a read-only evidence
 * preview — doc title, heading, the server-verified quote. Clicking opens the
 * action popover ("Show on terrain" / "View source"); the hover preview is
 * dismissed when the popover opens so only one surface shows at a time.
 *
 * Composed from the raw Radix primitives (not the ui/Popover + ui/Tooltip
 * wrappers) because both triggers must collapse onto the same button via
 * `asChild` — the wrappers each own their trigger slot and can't nest.
 * Content styling mirrors those wrappers so the surfaces stay consistent.
 */
export function CitationChip({
  citation,
  onFocusTerrain,
  onViewSource,
}: {
  citation: Citation;
  onFocusTerrain?: (target: TerrainFocusTarget) => void;
  onViewSource?: (target: SourceInspectorTarget) => void;
}) {
  const [open, setOpen] = useState(false); // click popover (action surface)
  const [preview, setPreview] = useState(false); // hover/focus card
  const meta = NODE_TYPE_META[citation.node_type];

  return (
    <RadixPopover.Root open={open} onOpenChange={setOpen}>
      <RadixTooltip.Root
        // Preview never coexists with the action popover: `!open` force-
        // closes it the moment a click opens the popover.
        open={preview && !open}
        onOpenChange={setPreview}
        disableHoverableContent={false}
      >
        <RadixTooltip.Trigger asChild>
          <RadixPopover.Trigger asChild>
            <button
              type="button"
              aria-label={`Citation ${citation.citation_id}: ${meta.display.toLowerCase()} ${citation.label}`}
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-sans text-[11px] text-ink",
                "border transition-colors cursor-pointer hover:bg-ink/5",
                meta.chip,
                provenanceClass(citation.edge_provenance),
              )}
            >
              <NodeTypeGlyph type={citation.node_type} className={meta.glyph} />
              <span className="font-medium">[{citation.citation_id}]</span>
              <span className="truncate max-w-[140px]">{citation.label}</span>
            </button>
          </RadixPopover.Trigger>
        </RadixTooltip.Trigger>
        <RadixTooltip.Portal>
          <RadixTooltip.Content
            side="top"
            align="start"
            sideOffset={6}
            className={cn(
              // Mirrors ui/Tooltip's surface styling.
              "z-50 max-w-xs",
              "bg-cream/95 backdrop-blur-sm border border-hair rounded-lg",
              "px-3 py-2 text-xs font-sans text-ink shadow-md",
              "data-[state=delayed-open]:animate-fade-in",
              "motion-reduce:animate-none",
            )}
          >
            <CitationHoverPreview citation={citation} />
          </RadixTooltip.Content>
        </RadixTooltip.Portal>
      </RadixTooltip.Root>
      <RadixPopover.Portal>
        <RadixPopover.Content
          side="top"
          align="start"
          sideOffset={6}
          collisionPadding={12}
          className={cn(
            // Mirrors ui/Popover's surface styling.
            "z-50 outline-none",
            // A citation with many passages can outgrow the viewport: cap at
            // the space Radix measured (already net of `collisionPadding`),
            // and at 60vh so one big group never owns the screen.
            "max-h-[min(var(--radix-popover-content-available-height),60vh)]",
            "overflow-y-auto overscroll-contain",
            "bg-cream border border-hair rounded-xl shadow-lg",
            "p-2 font-sans text-sm text-ink",
            "data-[state=open]:animate-fade-in",
            "motion-reduce:animate-none",
          )}
        >
          <CitationPopoverContent
            citations={[citation]}
            onFocusTerrain={
              onFocusTerrain &&
              ((target) => {
                onFocusTerrain(target);
                setOpen(false);
              })
            }
            onViewSource={
              onViewSource &&
              ((target) => {
                onViewSource(target);
                setOpen(false);
              })
            }
          />
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  );
}
