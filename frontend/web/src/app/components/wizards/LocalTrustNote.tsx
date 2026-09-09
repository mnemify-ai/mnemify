import type { ReactNode } from "react";
import { ShieldCheck } from "lucide-react";
import { cn } from "../../lib/cn";

/**
 * Calm local-first reassurance for the connect wizards, rendered right next
 * to the credential (or vault-path) input — where users actually hesitate —
 * rather than as a docs footnote. Mnemify is local-first, so the claim is
 * literal: tokens land in a local `.env` and never leave this machine.
 *
 * Keep the copy short and factual; the shield + sage tint do the calming.
 */
export function LocalTrustNote({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <p
      className={cn(
        "flex items-start gap-2.5 px-3.5 py-2.5 rounded-lg bg-sage/10 border border-sage/30 font-sans text-xs text-muted leading-relaxed",
        className,
      )}
    >
      <ShieldCheck
        size={14}
        strokeWidth={1.75}
        className="text-sage shrink-0 mt-px"
        aria-hidden="true"
      />
      <span>{children}</span>
    </p>
  );
}
