import type { ReactNode } from "react";
import { ExternalLink } from "lucide-react";
import { cn } from "../../lib/cn";

export interface SetupStep {
  /** What the user should do at this step. */
  title: ReactNode;
  /** Optional supporting copy. */
  body?: ReactNode;
  /** Optional external link displayed next to the title. */
  link?: { href: string; label: string };
}

interface WizardSetupStepsProps {
  steps: SetupStep[];
  /** Optional content rendered below the last step (e.g. a token input + test button). */
  children?: ReactNode;
  className?: string;
}

/**
 * Ordered "do these things in order" card list for connect wizards.
 * Numbered, in-brand, no GIFs or video — just clear steps + an optional
 * inline form below.
 */
export function WizardSetupSteps({ steps, children, className }: WizardSetupStepsProps) {
  return (
    <div className={cn("space-y-5", className)}>
      <ol className="space-y-3">
        {steps.map((step, i) => (
          <li
            key={i}
            className="flex items-start gap-3 px-4 py-3 rounded-xl bg-bone/40 border border-hair"
          >
            <span
              className="h-6 w-6 rounded-full bg-magenta/15 text-magenta font-serif text-sm flex items-center justify-center shrink-0 mt-0.5"
              aria-hidden
            >
              {i + 1}
            </span>
            <div className="flex-1 min-w-0">
              <p className="font-serif text-[15px] text-ink leading-snug">
                {step.title}
                {step.link && (
                  <>
                    {" "}
                    <a
                      href={step.link.href}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 font-sans text-xs text-magenta hover:underline align-middle"
                    >
                      {step.link.label}
                      <ExternalLink size={11} aria-hidden />
                    </a>
                  </>
                )}
              </p>
              {step.body && (
                <div className="font-sans text-xs text-muted mt-1 leading-relaxed">
                  {step.body}
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
      {children}
    </div>
  );
}
