import type { ReactNode } from "react";
import { HelpCircle } from "lucide-react";
import { Tooltip } from "../../components/ui/Tooltip";
import { cn } from "../../lib/cn";

interface SettingsSectionProps {
  /** Small uppercase label above the title. */
  eyebrow?: string;
  title: string;
  /**
   * Tooltip content shown when the user hovers/focuses the help icon next to
   * the title. Replaces the descriptive paragraph the old card layout used.
   */
  help?: ReactNode;
  /** Optional inline subhead rendered under the title (for short context). */
  description?: ReactNode;
  /** Right-aligned actions next to the title (e.g. a Reload button). */
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

/**
 * GitHub/Confluence-style settings section. Replaces the previous Card +
 * paragraph layout — long-form descriptions move into a `?` tooltip beside the
 * title so the page reads as a vertical column of sections separated by hair
 * dividers instead of a grid of bone-tinted boxes.
 */
export function SettingsSection({
  eyebrow,
  title,
  help,
  description,
  actions,
  children,
  className,
}: SettingsSectionProps) {
  return (
    <section
      className={cn(
        "py-8 first:pt-2 border-b border-hair last:border-b-0",
        className,
      )}
    >
      <header className="mb-5 flex items-start justify-between gap-4">
        <div className="min-w-0">
          {eyebrow && <p className="eyebrow mb-2">{eyebrow}</p>}
          <div className="flex items-center gap-2">
            <h2 className="font-serif text-xl text-ink leading-tight">{title}</h2>
            {help && (
              <Tooltip content={help} side="top">
                <button
                  type="button"
                  aria-label={`About ${title}`}
                  className="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted/70 hover:text-ink transition-colors focus:outline-none focus-visible:!shadow-none focus-visible:text-ink"
                >
                  <HelpCircle size={14} strokeWidth={1.5} aria-hidden />
                </button>
              </Tooltip>
            )}
          </div>
          {description && (
            <div className="font-sans text-sm text-muted mt-1.5 max-w-prose">
              {description}
            </div>
          )}
        </div>
        {actions && <div className="shrink-0 flex items-center gap-2">{actions}</div>}
      </header>
      <div>{children}</div>
    </section>
  );
}
