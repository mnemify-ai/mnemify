import type { HTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/cn";

const pillVariants = cva(
  "inline-flex items-center gap-2 px-3 py-1.5 rounded-full font-sans text-xs",
  {
    variants: {
      tone: {
        neutral: "glass-panel text-muted",
        success: "bg-success/12 border border-success/30 text-success",
        warning: "bg-warning/12 border border-warning/30 text-warning",
        info: "bg-info/40 border border-info/50 text-ink",
        danger: "bg-danger/12 border border-danger/30 text-danger",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

const dotColorByTone: Record<NonNullable<PillProps["tone"]>, string> = {
  neutral: "bg-muted",
  success: "bg-success",
  warning: "bg-warning",
  info: "bg-info",
  danger: "bg-danger",
};

export type PillProps = HTMLAttributes<HTMLDivElement> &
  VariantProps<typeof pillVariants> & {
    /** Prepend a small colored status dot matched to the tone. */
    dot?: boolean;
  };

/**
 * A small floating informational pill — used in TopBar for LastCompiledPill
 * and across connection cards for status indicators. Tones map to the
 * semantic color tokens (`success`, `warning`, `info`, `danger`) plus
 * `neutral` which uses the glass-panel surface.
 */
export function Pill({ className, tone, dot, children, ...props }: PillProps) {
  const resolvedTone = tone ?? "neutral";
  return (
    <div className={cn(pillVariants({ tone }), className)} {...props}>
      {dot && (
        <span
          aria-hidden="true"
          className={cn(
            "inline-block w-1.5 h-1.5 rounded-full shrink-0",
            dotColorByTone[resolvedTone],
          )}
        />
      )}
      {children}
    </div>
  );
}
