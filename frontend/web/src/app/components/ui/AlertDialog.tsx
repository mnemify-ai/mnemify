import * as RadixDialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { Button } from "./Button";
import { cn } from "../../lib/cn";

interface AlertDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Destructive (rose) vs default (magenta). */
  tone?: "destructive" | "default";
  onConfirm: () => void;
  confirming?: boolean;
  /** Extra content between the description and the buttons (e.g. a
   *  type-to-confirm field). */
  children?: ReactNode;
  /** Keep the confirm button disabled until some condition is met. */
  confirmDisabled?: boolean;
}

export function AlertDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "default",
  onConfirm,
  confirming,
  children,
  confirmDisabled = false,
}: AlertDialogProps) {
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
          className={cn(
            "fixed z-50 left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2",
            "w-[440px] max-w-[calc(100vw-2rem)]",
            "bg-cream border border-hair rounded-2xl shadow-xl outline-none",
            // Scale + fade enter (240ms). Radix unmounts on close so no exit anim.
            "data-[state=open]:animate-modal-in",
            "motion-reduce:animate-none",
          )}
        >
          <div className="p-7">
            <RadixDialog.Title className="font-serif text-xl text-ink mb-2">
              {title}
            </RadixDialog.Title>
            {description && (
              <RadixDialog.Description asChild>
                <div className="font-sans text-sm text-muted leading-relaxed">
                  {description}
                </div>
              </RadixDialog.Description>
            )}
            {children}
            <div className="flex items-center justify-end gap-2 mt-6">
              <Button
                variant="ghost"
                size="md"
                onClick={() => onOpenChange(false)}
                disabled={confirming}
              >
                {cancelLabel}
              </Button>
              <Button
                variant={tone === "destructive" ? "primary" : "primary"}
                size="md"
                onClick={onConfirm}
                disabled={confirming || confirmDisabled}
                className={
                  tone === "destructive"
                    ? "!bg-rose hover:!bg-rose/90 !text-cream"
                    : undefined
                }
              >
                {confirming ? "Working…" : confirmLabel}
              </Button>
            </div>
          </div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
