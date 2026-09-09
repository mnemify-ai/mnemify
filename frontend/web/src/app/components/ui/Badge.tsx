import type { HTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/cn";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 font-sans text-xs font-medium px-2.5 py-0.5 rounded-full border whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "bg-bone/80 text-ink border-hair",
        magenta: "bg-magenta/12 text-magenta border-magenta/30",
        sage: "bg-sage/12 text-sage border-sage/30",
        rose: "bg-rose/12 text-rose border-rose/30",
        muted: "bg-transparent text-muted border-hair",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type BadgeProps = HTMLAttributes<HTMLSpanElement> &
  VariantProps<typeof badgeVariants>;

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
