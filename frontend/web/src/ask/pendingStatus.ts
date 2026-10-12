// What a pending answer says before its first token (#26). The server sends a
// `status` event as each stage starts (understanding → searching → reading →
// writing; "thinking" on the agentic path). Until the first one lands — or
// from an older server that sends none — the label stays neutral, and
// citations, once they arrive, mean we are reading.

import type { AskStatus } from "./types";

/** Seconds of silence before the elapsed counter appears. */
export const ELAPSED_AFTER_S = 5;

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function pendingLabel(status: AskStatus | undefined, citationCount: number): string {
  switch (status?.stage) {
    case "understanding":
      return "Understanding your question…";
    case "searching":
      return "Searching your notes…";
    case "reading":
      return status.count ? `Reading ${plural(status.count, "document")}…` : "Reading what I found…";
    case "writing":
      return "Writing the answer…";
    case "thinking":
      return "Thinking…";
  }
  if (citationCount <= 0) return "Thinking…";
  return `Reading ${plural(citationCount, "source")}…`;
}

/** "· 12s" once the wait passes ELAPSED_AFTER_S, else "". */
export function elapsedLabel(seconds: number): string {
  return seconds >= ELAPSED_AFTER_S ? `· ${Math.floor(seconds)}s` : "";
}
