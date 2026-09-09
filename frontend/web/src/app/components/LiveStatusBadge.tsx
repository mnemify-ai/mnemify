import { cn } from "../lib/cn";
import { relativeTime } from "../lib/relativeTime";
import type { Connection } from "../api/connections";

interface LiveStatusBadgeProps {
  connection: Connection;
  className?: string;
}

/**
 * "Live · 14 docs · 2m ago" — the small monospace pill that surfaces real
 * harvest status next to mock-derived numbers. Returns null if the
 * connection has never been harvested.
 */
export function LiveStatusBadge({ connection, className }: LiveStatusBadgeProps) {
  if (connection.doc_count === 0 || !connection.last_harvest_at) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full",
        "bg-sage/10 border border-sage/30 font-mono text-[11px] text-sage",
        className,
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-sage" aria-hidden />
      Live · {connection.doc_count.toLocaleString()} docs ·{" "}
      {relativeTime(connection.last_harvest_at)}
    </span>
  );
}
