// Graceful fallback when no other renderer matches the attachment's MIME/ext.
// Shows the file's metadata in serif chrome with a primary Download button
// and a secondary "Open in new tab" link. Always last in the registry.

import { useEffect } from "react";
import { Download, ExternalLink, FileText } from "lucide-react";
import { Button } from "../../ui/Button";
import type { RendererProps } from "../registry";

function humanBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export default function UnsupportedRenderer({
  attachment,
  downloadUrl,
  onChrome,
}: RendererProps) {
  useEffect(() => {
    // No chrome (no pagination / zoom / sheets). Footer renders empty.
    onChrome({});
  }, [onChrome]);

  return (
    <div className="flex-1 min-h-0 flex items-center justify-center px-6 py-12 overflow-y-auto">
      <div className="flex flex-col items-center text-center max-w-[44ch]">
        <div className="w-16 h-16 rounded-2xl bg-bone/70 border border-hair flex items-center justify-center mb-5">
          <FileText size={28} strokeWidth={1.4} className="text-muted" aria-hidden />
        </div>
        <h3 className="font-serif text-xl text-ink leading-tight break-all">
          {attachment.name}
        </h3>
        <p className="font-mono text-[11px] text-muted mt-2">
          {attachment.mime || "unknown type"} · {humanBytes(attachment.size_bytes)}
        </p>
        <p className="font-sans text-sm text-muted mt-4 leading-relaxed">
          In-app preview isn't available for this format yet. Download the file
          to open it in its native application.
        </p>
        <div className="mt-6 flex items-center gap-2">
          <Button
            variant="primary"
            size="md"
            type="button"
            onClick={() => {
              // Use a hidden anchor with `download` so the browser keeps the
              // original filename and treats it as a download (the attachment
              // disposition on the downloadUrl backs this up).
              const a = document.createElement("a");
              a.href = downloadUrl;
              a.download = attachment.name;
              a.rel = "noopener";
              document.body.appendChild(a);
              a.click();
              a.remove();
            }}
          >
            <Download size={14} strokeWidth={1.75} aria-hidden />
            Download
          </Button>
          <a
            href={downloadUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 h-10 px-4 rounded-full font-sans font-medium text-sm text-ink hover:bg-bone/60 transition-colors"
          >
            <ExternalLink size={14} strokeWidth={1.75} aria-hidden />
            Open in new tab
          </a>
        </div>
      </div>
    </div>
  );
}
