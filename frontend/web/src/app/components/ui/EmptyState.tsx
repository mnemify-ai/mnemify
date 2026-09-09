import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

export interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

/**
 * Centered empty-state slot. Use when a list or panel has no items but no
 * error condition either. For error variants use `ErrorState`.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center text-center mx-auto",
        "max-w-[48ch] py-8 md:py-12 px-4",
        className,
      )}
    >
      {icon && (
        <div className="text-muted mb-4 flex items-center justify-center">
          {icon}
        </div>
      )}
      <h3 className="font-serif text-xl text-ink leading-tight">{title}</h3>
      {description && (
        <p className="font-sans text-sm text-muted mt-2 leading-relaxed">
          {description}
        </p>
      )}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}
