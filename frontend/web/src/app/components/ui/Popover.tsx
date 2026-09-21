import * as RadixPopover from "@radix-ui/react-popover";
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

interface PopoverProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Trigger element. Uses Radix's `asChild` so the trigger's own ref + a11y
   *  attrs are preserved. */
  trigger: ReactNode;
  children: ReactNode;
  side?: RadixPopover.PopoverContentProps["side"];
  align?: RadixPopover.PopoverContentProps["align"];
  sideOffset?: number;
  className?: string;
}

/**
 * Lightweight Radix popover wrapper styled to match `ui/Tooltip` and
 * `ui/Dialog`. Used by the PDF viewer's zoom menu — anywhere we need an
 * anchored panel with viewport-edge collision handling.
 */
export function Popover({
  open,
  onOpenChange,
  trigger,
  children,
  side = "bottom",
  align = "end",
  sideOffset = 6,
  className,
}: PopoverProps) {
  return (
    <RadixPopover.Root open={open} onOpenChange={onOpenChange}>
      <RadixPopover.Trigger asChild>{trigger}</RadixPopover.Trigger>
      <RadixPopover.Portal>
        <RadixPopover.Content
          side={side}
          align={align}
          sideOffset={sideOffset}
          className={cn(
            "z-50 outline-none",
            // Radix reports how much room is left between the anchor and the
            // viewport edge; cap at that and scroll inside so a tall menu (the
            // 14-row model picker) never runs off a short window.
            "max-h-[var(--radix-popover-content-available-height)] overflow-y-auto overscroll-contain",
            "bg-cream border border-hair rounded-xl shadow-lg",
            "p-2 font-sans text-sm text-ink",
            "data-[state=open]:animate-fade-in",
            "motion-reduce:animate-none",
            className,
          )}
        >
          {children}
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  );
}
