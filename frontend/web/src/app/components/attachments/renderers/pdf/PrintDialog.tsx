import { useState } from "react";
import { Printer } from "lucide-react";
import { Dialog, DialogClose } from "../../../ui/Dialog";
import { Button } from "../../../ui/Button";

interface PrintDialogProps {
  open: boolean;
  inlineUrl: string;
  filename: string;
  onClose: () => void;
}

/**
 * Tiny confirm before invoking the browser print dialog. We could fire
 * `print()` straight from the toolbar button, but most users don't know the
 * browser's print dialog already exposes page-range — surfacing that here
 * means we ship a useful viewer without building a custom range selector.
 *
 * Implementation: a hidden iframe pointed at `inlineUrl`. On load we call
 * `print()` against its contentWindow; on `afterprint` we tear the iframe
 * down. Falls back to opening the PDF in a new tab if the iframe approach
 * fails (some browsers refuse to print sandboxed PDFs).
 */
export function PrintDialog({
  open,
  inlineUrl,
  filename,
  onClose,
}: PrintDialogProps) {
  const [printing, setPrinting] = useState(false);

  function startPrint() {
    setPrinting(true);
    const iframe = document.createElement("iframe");
    iframe.style.position = "fixed";
    iframe.style.right = "0";
    iframe.style.bottom = "0";
    iframe.style.width = "0";
    iframe.style.height = "0";
    iframe.style.border = "0";
    iframe.setAttribute("aria-hidden", "true");
    iframe.src = inlineUrl;

    let cleaned = false;
    function cleanup() {
      if (cleaned) return;
      cleaned = true;
      iframe.remove();
      setPrinting(false);
      onClose();
    }

    iframe.onload = () => {
      // Give pdf.js inside the iframe a tick to register before printing.
      window.setTimeout(() => {
        try {
          iframe.contentWindow?.focus();
          iframe.contentWindow?.print();
        } catch {
          // Fallback: open the PDF in a new tab so the user can still print.
          window.open(inlineUrl, "_blank", "noopener");
          cleanup();
          return;
        }
        // The browser's print dialog is modal; we wait for it to close.
        const onAfterPrint = () => {
          iframe.contentWindow?.removeEventListener("afterprint", onAfterPrint);
          cleanup();
        };
        iframe.contentWindow?.addEventListener("afterprint", onAfterPrint);
        // Safety net — some browsers don't dispatch afterprint in iframes.
        window.setTimeout(cleanup, 60_000);
      }, 50);
    };
    iframe.onerror = cleanup;
    document.body.appendChild(iframe);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => !v && onClose()}
      ariaLabel="Print PDF"
      width="440px"
    >
      <DialogClose onClose={onClose} />
      <div className="px-6 pt-6 pb-5">
        <p className="eyebrow mb-1">Print</p>
        <h3
          className="font-serif text-xl text-ink leading-snug truncate pr-8"
          title={filename}
        >
          {filename}
        </h3>
        <p className="font-sans text-sm text-muted mt-3 leading-relaxed">
          Your browser's print dialog will open. Use its page-range option to
          print specific pages.
        </p>
      </div>
      <div className="px-6 pb-5 pt-2 flex items-center justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          size="md"
          onClick={onClose}
          disabled={printing}
        >
          Cancel
        </Button>
        <Button
          type="button"
          variant="primary"
          size="md"
          onClick={startPrint}
          loading={printing}
        >
          <Printer size={14} strokeWidth={1.75} aria-hidden />
          Print
        </Button>
      </div>
    </Dialog>
  );
}
