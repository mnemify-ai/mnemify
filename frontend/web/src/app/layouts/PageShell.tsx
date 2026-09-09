import type { ReactNode } from "react";
import { cn } from "../lib/cn";

interface PageShellProps {
  title: string;
  eyebrow?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  /** Section nav (e.g. <HarvestSectionTabs />). Rendered above the heading so
   *  the title stays the dominant landmark and the tabs read as a quiet
   *  section indicator. */
  tabs?: ReactNode;
  children: ReactNode;
  className?: string;
  noDivider?: boolean;
}

export function PageShell({
  title,
  eyebrow,
  description,
  actions,
  tabs,
  children,
  className,
  noDivider,
}: PageShellProps) {
  return (
    <div
      className={cn(
        // Fluid horizontal padding: 20px on small viewports up to 40px at
        // wide ones, scaling with viewport width rather than the old
        // `px-6 lg:px-10` step at the lg breakpoint. The container still
        // caps at `max-w-page` (lifted to 1680px in tailwind.config.ts).
        "max-w-page mx-auto px-[clamp(1.25rem,3vw,2.5rem)] pt-24 pb-20",
        className,
      )}
    >
      {tabs && <div className="mb-6">{tabs}</div>}
      <header
        className={cn(
          "flex items-end justify-between gap-6",
          noDivider ? "mb-6" : "mb-10 pb-8 border-b border-hair",
        )}
      >
        <div>
          {eyebrow && <p className="eyebrow mb-3">{eyebrow}</p>}
          {/* Fluid display heading — ~36px on a 12" laptop, ~60px on a wide
              monitor, scaling continuously between (no `lg:` step). */}
          <h1 className="display text-[clamp(2.25rem,4vw,3.75rem)] text-ink">
            {title}
          </h1>
          {description && (
            <p className="font-sans text-muted mt-4 max-w-prose">{description}</p>
          )}
        </div>
        {actions && <div className="flex items-center gap-3">{actions}</div>}
      </header>
      {children}
    </div>
  );
}
