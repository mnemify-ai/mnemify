import * as RadixDialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "../../lib/cn";

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
  /** Width in pixels or any CSS value. Default 540px. */
  width?: string;
  className?: string;
  /** Accessible label for the dialog as a whole. Hidden visually. */
  ariaLabel?: string;
}

export function Dialog({
  open,
  onOpenChange,
  children,
  width = "540px",
  className,
  ariaLabel = "Dialog",
}: DialogProps) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay
          className={cn(
            "fixed inset-0 z-50 bg-ink/30 backdrop-blur-sm",
            "data-[state=open]:animate-fade-in",
            "motion-reduce:animate-none",
          )}
        />
        <RadixDialog.Content
          aria-describedby={undefined}
          className={cn(
            "fixed z-50 left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2",
            "bg-cream border border-hair rounded-3xl shadow-2xl",
            "max-h-[88vh] flex flex-col outline-none",
            // Modal motion: scale 0.96→1 + fade (240ms). Radix unmounts on close,
            // so we don't fight the lib for a close-anim — enter-only is fine.
            "data-[state=open]:animate-modal-in",
            "motion-reduce:animate-none",
            className,
          )}
          style={{ width, maxWidth: "calc(100vw - 2rem)" }}
        >
          <RadixDialog.Title className="sr-only">{ariaLabel}</RadixDialog.Title>
          {children}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

interface DialogCloseProps {
  onClose: () => void;
  className?: string;
}

export function DialogClose({ onClose, className }: DialogCloseProps) {
  return (
    <button
      type="button"
      aria-label="Close dialog"
      onClick={onClose}
      className={cn(
        // p-3 + 16px icon ≈ 40px box; before:inset-[-4px] expands the hit area
        // to ≥44px without altering the visual chrome.
        "absolute top-3 right-3 p-3 rounded-full text-muted hover:text-ink hover:bg-bone/80 transition-colors",
        "before:content-[''] before:absolute before:inset-[-4px]",
        className,
      )}
    >
      <X size={16} strokeWidth={1.5} />
    </button>
  );
}
