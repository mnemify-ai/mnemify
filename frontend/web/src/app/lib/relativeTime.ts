import { formatDistanceToNowStrict } from "date-fns";
import { RELATIVE_TIME_JUST_NOW_THRESHOLD_MS } from "./constants";

/**
 * Format an ISO timestamp as a short, human-readable relative time.
 * Examples: "4h ago", "3d ago", "just now".
 */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const ms = Date.now() - date.getTime();
  if (ms < RELATIVE_TIME_JUST_NOW_THRESHOLD_MS) return "just now";
  const formatted = formatDistanceToNowStrict(date, { addSuffix: false });
  return `${formatted} ago`
    .replace(" seconds", "s")
    .replace(" second", "s")
    .replace(" minutes", "m")
    .replace(" minute", "m")
    .replace(" hours", "h")
    .replace(" hour", "h")
    .replace(" days", "d")
    .replace(" day", "d")
    .replace(" months", "mo")
    .replace(" month", "mo")
    .replace(" years", "y")
    .replace(" year", "y");
}
