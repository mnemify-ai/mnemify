// Attachment-renderer registry.
//
// Each format has its own renderer file under ./renderers/, loaded lazily so
// a heavy lib (pdf.js, sheetjs, mammoth) only downloads the first time a
// user opens that kind of file. Adding a format = appending one entry.
//
// Order matters: `canHandle` runs in array order; the final UnsupportedRenderer
// matches everything as a graceful fallback.

import type { ComponentType, ReactNode } from "react";
import type { DocAttachment } from "../../api/documents";

export interface ChromeState {
  pagination?: {
    current: number;
    total: number;
    goto: (page: number) => void;
  };
  sheets?: {
    names: string[];
    active: number;
    select: (index: number) => void;
  };
  zoom?: {
    value: number;
    set: (z: number) => void;
    fitWidth: () => void;
  };
  /**
   * Renderer-owned find handler. AttachmentViewer's Cmd/Ctrl-F intercepts
   * the browser shortcut and calls this when set — used by the PDF renderer
   * to open its in-document search panel (browser Cmd-F doesn't work on
   * virtualized off-screen pages).
   */
  onFind?: () => void;
  /** Optional renderer-supplied custom footer fragment. */
  footerExtra?: ReactNode;
}

export interface RendererProps {
  attachment: DocAttachment;
  /** Full URL the renderer can hand to <iframe>/<img>/pdf.js. */
  inlineUrl: string;
  /** Full URL preserving the download disposition for "Download" buttons. */
  downloadUrl: string;
  /** Renderer reports pagination/zoom/sheet-tabs up to the modal chrome. */
  onChrome: (chrome: ChromeState) => void;
}

export interface AttachmentRenderer {
  id: string;
  canHandle: (att: DocAttachment) => boolean;
  load: () => Promise<{ default: ComponentType<RendererProps> }>;
}

export const registry: AttachmentRenderer[] = [
  {
    id: "pdf",
    canHandle: (a) =>
      /pdf$/i.test(a.mime) || a.name.toLowerCase().endsWith(".pdf"),
    load: () => import("./renderers/PdfRenderer"),
  },
  {
    id: "spreadsheet",
    canHandle: (a) =>
      /sheet|excel|csv/i.test(a.mime) || /\.(xlsx|xls|csv)$/i.test(a.name),
    load: () => import("./renderers/spreadsheet/SpreadsheetRenderer"),
  },
  {
    id: "docx",
    canHandle: (a) =>
      /wordprocessingml/i.test(a.mime) || /\.docx?$/i.test(a.name),
    load: () => import("./renderers/DocxRenderer"),
  },
  {
    id: "video",
    // Only the container formats browsers can actually decode. .avi/.mkv fall
    // through to UnsupportedRenderer (download) since <video> can't play them.
    canHandle: (a) =>
      /^video\//i.test(a.mime) || /\.(mp4|mov|m4v|webm|ogv)$/i.test(a.name),
    load: () => import("./renderers/VideoRenderer"),
  },
  {
    id: "unsupported",
    canHandle: () => true,
    load: () => import("./renderers/UnsupportedRenderer"),
  },
];

export function pickRenderer(att: DocAttachment): AttachmentRenderer {
  // The trailing Unsupported entry guarantees a match — non-null assertion is safe.
  return registry.find((r) => r.canHandle(att))!;
}

// Once we've kicked off a chunk import, the module is cached; further calls
// to entry.load() reuse the same promise. We still memoize here so a hover
// over 200 attachments doesn't churn 200 promise references.
const preloaded = new Set<string>();

/**
 * Fire-and-forget: starts downloading the renderer chunk for this attachment
 * before the user clicks it. Called from hover/focus on attachment list rows
 * so the lazy chunk + pdf.js worker land in cache while the user decides to
 * open the file. No-op if already triggered.
 */
export function preloadRenderer(att: DocAttachment): void {
  const entry = pickRenderer(att);
  if (preloaded.has(entry.id)) return;
  preloaded.add(entry.id);
  void entry.load();
}
