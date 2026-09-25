import type { ReactNode } from "react";
import { Dialog, DialogClose } from "../ui/Dialog";
import { Button } from "../ui/Button";
import { sourceMeta } from "../SourceBadge";
import { cn } from "../../lib/cn";

interface WizardModalProps {
  source: string;
  open: boolean;
  onClose: () => void;
  step: number;          // 1-indexed
  totalSteps: number;
  title: string;
  eyebrow?: string;
  /** Disable Continue when validation hasn't passed. */
  continueDisabled?: boolean;
  continueLabel?: string;
  /** Right-action handler. Final step's handler typically does the Save. */
  onContinue: () => void;
  /** Hidden on step 1; otherwise navigates back. */
  onBack?: () => void;
  /** Loading state for the right action button. */
  pending?: boolean;
  children: ReactNode;
}

export function WizardModal({
  source,
  open,
  onClose,
  step,
  totalSteps,
  title,
  eyebrow,
  continueDisabled,
  continueLabel,
  onContinue,
  onBack,
  pending,
  children,
}: WizardModalProps) {
  const meta = sourceMeta(source);
  const isFirst = step === 1;
  const isFinal = step === totalSteps;

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => !v && onClose()}
      ariaLabel={`${meta.verb.add} ${meta.label}`}
      width="560px"
    >
      <DialogClose onClose={onClose} />
      <header className="px-7 pt-7 pb-5 border-b border-hair shrink-0">
        <div className="flex items-center gap-3 mb-4">
          <span
            className={cn(
              "h-8 w-8 rounded-lg flex items-center justify-center shrink-0",
              meta.dotClass,
            )}
          >
            <span className="font-serif italic text-cream text-base">
              {meta.label.charAt(0)}
            </span>
          </span>
          <span className="font-serif text-lg text-ink">{meta.verb.add} {meta.label}</span>
        </div>
        <StepIndicator current={step} total={totalSteps} />
        {eyebrow && <p className="eyebrow mt-4 mb-1">{eyebrow}</p>}
        <h2 className="font-serif text-2xl text-ink leading-tight tracking-tight">
          {title}
        </h2>
      </header>

      <div className="px-7 py-6 overflow-y-auto flex-1 min-h-0">{children}</div>

      <footer className="px-7 py-4 border-t border-hair flex items-center justify-between gap-3 shrink-0">
        {!isFirst && onBack ? (
          <Button variant="ghost" size="md" onClick={onBack} disabled={pending}>
            ← Back
          </Button>
        ) : (
          <span />
        )}
        <Button
          variant="primary"
          size="md"
          onClick={onContinue}
          disabled={continueDisabled || pending}
        >
          {continueLabel ?? (isFinal ? "Save" : "Continue")}
          {pending ? null : isFinal ? null : <span aria-hidden>→</span>}
        </Button>
      </footer>
    </Dialog>
  );
}

function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div
      role="status"
      aria-label={`Step ${current} of ${total}`}
      className="flex items-center gap-2"
    >
      <span className="font-sans text-[11px] uppercase tracking-eyebrow text-muted">
        Step {current} of {total}
      </span>
      <span aria-hidden className="flex items-center gap-1.5 ml-1">
        {Array.from({ length: total }).map((_, i) => (
          <span
            key={i}
            className={cn(
              "h-1.5 rounded-full transition-all",
              i + 1 === current ? "w-6 bg-magenta" : "w-1.5 bg-line/20",
            )}
          />
        ))}
      </span>
    </div>
  );
}
