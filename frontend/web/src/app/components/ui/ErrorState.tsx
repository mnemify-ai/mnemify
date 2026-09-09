import type { ReactNode } from "react";
import { AlertCircle } from "lucide-react";
import { Button } from "./Button";
import { cn } from "../../lib/cn";

export interface ErrorStateProps {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  /** When provided, renders a "Try again" button below the action slot. */
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
}

/**
 * Centered error-state slot. Same shape as `EmptyState` but title is rendered
 * in the danger tone and the default icon is `AlertCircle`. Pass `onRetry` to
 * surface a retry button using the standard `Button` primitive.
 */
export function ErrorState({
  icon,
  title,
  description,
  action,
  onRetry,
  retryLabel = "Try again",
  className,
}: ErrorStateProps) {
  const resolvedIcon =
    icon !== undefined ? icon : <AlertCircle size={28} strokeWidth={1.5} />;

  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center text-center mx-auto",
        "max-w-[48ch] py-8 md:py-12 px-4",
        className,
      )}
    >
      {resolvedIcon && (
        <div className="text-danger mb-4 flex items-center justify-center">
          {resolvedIcon}
        </div>
      )}
      <h3 className="font-serif text-xl text-danger leading-tight">{title}</h3>
      {description && (
        <p className="font-sans text-sm text-muted mt-2 leading-relaxed">
          {description}
        </p>
      )}
      {(action || onRetry) && (
        <div className="mt-6 flex items-center justify-center gap-2">
          {action}
          {onRetry && (
            <Button variant="secondary" size="md" onClick={onRetry}>
              {retryLabel}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
