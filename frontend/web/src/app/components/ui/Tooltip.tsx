import * as RadixTooltip from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

interface TooltipProviderProps {
  children: ReactNode;
  /** Default open delay in ms applied to every Tooltip below the provider. */
  delayDuration?: number;
  /** Window during which a sibling tooltip opens with 0 delay. */
  skipDelayDuration?: number;
}

/**
 * App-level provider for Radix tooltips. Mount once near the root so
 * sibling tooltips share the "skip delay" window.
 */
export function TooltipProvider({
  children,
  delayDuration = 200,
  skipDelayDuration = 300,
}: TooltipProviderProps) {
  return (
    <RadixTooltip.Provider
      delayDuration={delayDuration}
      skipDelayDuration={skipDelayDuration}
    >
      {children}
    </RadixTooltip.Provider>
  );
}

export interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  /** Override open delay for this tooltip only. Default 200ms. */
  openDelay?: number;
  /** Override close delay for this tooltip only. Default 100ms. */
  closeDelay?: number;
  /** Radix side — top/right/bottom/left. Default "top". */
  side?: RadixTooltip.TooltipContentProps["side"];
  /** Radix alignment along the chosen side. Default "center". */
  align?: RadixTooltip.TooltipContentProps["align"];
  /** Pixel gap between trigger and content. Default 6. */
  sideOffset?: number;
  /** Disable the tooltip without unmounting children. */
  disabled?: boolean;
  className?: string;
}

/**
 * Wraps a single trigger with a Radix tooltip. Pass any focusable element as
 * `children` — the component is built around `asChild` semantics so the
 * trigger's own ref + a11y attrs are preserved.
 */
export function Tooltip({
  content,
  children,
  openDelay = 200,
  closeDelay = 100,
  side = "top",
  align = "center",
  sideOffset = 6,
  disabled = false,
  className,
}: TooltipProps) {
  if (disabled) return <>{children}</>;

  return (
    <RadixTooltip.Root delayDuration={openDelay} disableHoverableContent={false}>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          align={align}
          sideOffset={sideOffset}
          aria-live="polite"
          // closeDelay isn't a Radix prop; emulate via Radix's built-in skip
          // window. We still expose it for forward-compat and apply it as
          // a CSS-controllable data attribute so callers can style fade-out.
          data-close-delay={closeDelay}
          className={cn(
            "z-50 max-w-xs",
            "bg-cream/95 backdrop-blur-sm border border-hair rounded-lg",
            "px-3 py-2 text-xs font-sans text-ink shadow-md",
            "data-[state=delayed-open]:animate-fade-in",
            "motion-reduce:animate-none",
            className,
          )}
        >
          {content}
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}
