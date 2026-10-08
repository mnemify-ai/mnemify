import { Folder, BookOpen } from "lucide-react";
import { sourceMeta } from "../SourceBadge";
import { cn } from "../../lib/cn";

/**
 * Brand glyph for a source, in a tinted circle — the mockup's row icons.
 * Notion and Confluence get inline marks; local folders and Obsidian get
 * lucide icons; anything else falls back to the source's colour dot.
 */
export function SourceIcon({ source, size = 32, className }: { source: string; size?: number; className?: string }) {
  const meta = sourceMeta(source);
  const inner = Math.round(size * 0.5);
  return (
    <span
      className={cn("inline-grid shrink-0 place-items-center rounded-full border border-hair bg-cream", className)}
      style={{ width: size, height: size }}
      title={meta.label}
      aria-hidden
    >
      {source === "notion" ? (
        <svg width={inner} height={inner} viewBox="0 0 24 24" fill="none">
          <rect x="3" y="3" width="18" height="18" rx="2.5" stroke="currentColor" strokeWidth="1.6" className="text-ink" />
          <path d="M7.5 17V7.5l7.5 9.5V7.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className="text-ink" />
        </svg>
      ) : source === "confluence" ? (
        <svg width={inner} height={inner} viewBox="0 0 24 24" fill="none">
          <path d="M3.5 17.5c2.2-3.6 4.2-5.5 7.2-5.5 2.6 0 4.4 1.3 7.3 3.1l2.5 1.6" stroke="#2563EB" strokeWidth="2.2" strokeLinecap="round" />
          <path d="M20.5 6.5c-2.2 3.6-4.2 5.5-7.2 5.5-2.6 0-4.4-1.3-7.3-3.1L3.5 7.3" stroke="#2563EB" strokeWidth="2.2" strokeLinecap="round" />
        </svg>
      ) : source === "obsidian" ? (
        <BookOpen size={inner} strokeWidth={1.75} className="text-[#7E66E3]" />
      ) : source === "localfiles" ? (
        <Folder size={inner} strokeWidth={1.75} className="text-[#B45309]" />
      ) : (
        <span className={cn("rounded-full", meta.dotClass)} style={{ width: inner * 0.5, height: inner * 0.5 }} />
      )}
    </span>
  );
}
