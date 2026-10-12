/**
 * The sample workspace lives under /sample and reuses the real pages. Those
 * pages link with absolute app paths ("/regions/x", "/?tag=y"); inside the
 * sample, the ones the sample can show are rewritten to stay in it. Anything
 * else (Build, Settings) leaves the sample on purpose: that's the way out.
 */
export const SAMPLE_BASE = "/sample";

const SAMPLE_ROOTS = ["/regions", "/action-items", "/documents"];

/** The sample's version of an app href, or null when it has none. */
export function toSamplePath(href: string): string | null {
  if (!href.startsWith("/") || href.startsWith("//")) return null;
  if (href === SAMPLE_BASE || href.startsWith(`${SAMPLE_BASE}/`) || href.startsWith(`${SAMPLE_BASE}?`)) {
    return href;
  }
  // "/", "/?tag=…", "/#…" → the sample map.
  if (href === "/" || href.startsWith("/?") || href.startsWith("/#")) {
    return `${SAMPLE_BASE}${href.slice(1)}`;
  }
  for (const root of SAMPLE_ROOTS) {
    if (href === root || href.startsWith(`${root}/`) || href.startsWith(`${root}?`)) {
      return `${SAMPLE_BASE}${href}`;
    }
  }
  return null;
}

/** The sample's map page (tolerates a trailing slash). */
export function isSampleHome(pathname: string): boolean {
  return pathname.replace(/\/+$/, "") === SAMPLE_BASE;
}

export function isSamplePath(pathname: string): boolean {
  return pathname === SAMPLE_BASE || pathname.startsWith(`${SAMPLE_BASE}/`);
}
