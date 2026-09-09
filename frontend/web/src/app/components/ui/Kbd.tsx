import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

interface KbdProps extends HTMLAttributes<HTMLElement> {
  children: ReactNode;
}

/**
 * Inline keyboard shortcut indicator. Use for hint glyphs like ⌘K, ⌘/, S, C, R.
 */
export function Kbd({ children, className, ...rest }: KbdProps) {
  return (
    <kbd
      className={cn(
        "inline-flex items-center justify-center",
        "bg-bone border border-hair rounded",
        "px-1.5 py-0.5 text-[11px] font-mono text-muted",
        "min-w-[1.5em] leading-none",
        className,
      )}
      {...rest}
    >
      {children}
    </kbd>
  );
}
