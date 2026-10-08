import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * The workspace's card: an eyebrow (or serif title) row with an optional
 * right-hand action, then the body. Every block on the Overview is one.
 */
export function SectionCard({
  eyebrow,
  title,
  description,
  action,
  children,
  className,
  bodyClassName,
}: {
  eyebrow?: ReactNode;
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cn("rounded-2xl border border-hair bg-bone/40", className)}>
      {(eyebrow || title || action) && (
        <header className="flex items-start justify-between gap-4 px-5 pt-4">
          <div className="min-w-0">
            {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
            {title ? <h2 className="font-serif text-xl text-ink leading-tight">{title}</h2> : null}
            {description ? <p className="font-sans text-sm text-muted mt-1">{description}</p> : null}
          </div>
          {action ? <div className="shrink-0 font-sans text-sm">{action}</div> : null}
        </header>
      )}
      <div className={cn("px-5 pb-5 pt-3", bodyClassName)}>{children}</div>
    </section>
  );
}

/** "View all →" style link used in card headers. */
export function CardLink({ children, className, ...props }: React.ComponentProps<"a"> & { children: ReactNode }) {
  return (
    <a
      {...props}
      className={cn("inline-flex items-center gap-1 font-sans text-sm text-magenta hover:underline underline-offset-4", className)}
    >
      {children}
    </a>
  );
}
