/**
 * Format a number of seconds as a compact ETA: "17s", "4m", "1h 12m".
 * Returns "—" for null / non-finite inputs.
 */
export function formatEta(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) {
    const s = Math.round(seconds % 60);
    return s ? `${m}m ${s}s` : `${m}m`;
  }
  const h = Math.floor(m / 60);
  const mins = m % 60;
  return mins ? `${h}h ${mins}m` : `${h}h`;
}

/** Total seconds estimated from current rate + remaining docs. */
export function computeEtaSeconds(
  done: number,
  total: number,
  rate: number | null | undefined,
): number | null {
  if (!rate || rate <= 0) return null;
  const remaining = Math.max(0, total - done);
  if (remaining === 0) return 0;
  return remaining / rate;
}

/** Bytes-projected ETA: project remaining bytes from the running mean of
 *  bytes-per-doc, then divide by bytes/sec. Used for sources whose per-doc
 *  cost varies by orders of magnitude (Notion pages with deep block trees)
 *  — the docs/sec rate visibly stalls each time a heavy doc lands, but
 *  bytes/sec stays smoother, so the ETA is steadier and projects more
 *  honestly. Returns ``null`` if any input is missing or non-positive.
 */
export function computeBytesEtaSeconds(
  done: number,
  total: number,
  bytesRate: number | null | undefined,
  avgBytesPerDoc: number | null | undefined,
): number | null {
  if (!bytesRate || bytesRate <= 0) return null;
  if (!avgBytesPerDoc || avgBytesPerDoc <= 0) return null;
  const remaining = Math.max(0, total - done);
  if (remaining === 0) return 0;
  return (remaining * avgBytesPerDoc) / bytesRate;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return s ? `${m}m ${s}s` : `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}
