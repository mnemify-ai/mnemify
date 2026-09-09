// HTML renderer for the document viewer — Confluence ships its body as
// XHTML storage format, so the viewer rewrites Confluence-specific custom
// elements (structured-macros, ac:link, ac:image, ac:emoticon, layout
// wrappers) into plain HTML the browser can render, sanitizes the result,
// and prints it inside the `doc-viewer-html` prose CSS in theme/index.css.
//
// Why string-level rewrites instead of DOM parsing: the storage format
// uses XML-namespaced tags (`ac:`, `ri:`) that browsers parse as bogus
// inline elements, so the only safe operation on the DOM side is "drop
// them or unwrap them" — there's no event hook to convert them into
// renderable HTML. Doing it pre-parse on the string keeps fidelity.

import { useMemo } from "react";
import { apiUrl } from "../api/client";
import type { DocAttachment } from "../api/documents";
import { sanitizeHtml } from "../lib/sanitizeHtml";

function escapeAttr(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeText(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/** Look up a Confluence-style filename reference against the document's
 *  attachment list and return a renderable URL. Absolute http(s)/data/root
 *  paths pass through; everything else is matched on `DocAttachment.name`
 *  (the original source-side filename). */
function resolveImageSrc(src: string, attachments?: DocAttachment[]): string | null {
  if (!src) return null;
  if (
    src.startsWith("http://") ||
    src.startsWith("https://") ||
    src.startsWith("data:") ||
    src.startsWith("/")
  ) {
    return src;
  }
  const hit = attachments?.find((a) => a.name === src);
  return hit ? apiUrl(hit.url) : null;
}

const ADMONITION_EMOJI: Record<string, string> = {
  info: "ℹ️",
  note: "📝",
  warning: "⚠️",
  tip: "💡",
};

const DIAGRAM_MACROS = new Set(["drawio", "gliffy", "lucidchart"]);
const DYNAMIC_MACROS = new Set([
  "recently-updated",
  "blog-posts",
  "children-display",
  "contributors",
  "pagetree",
  "toc",
  "include",
  "excerpt-include",
]);

/** Pull a named ``<ac:parameter ac:name="X">value</ac:parameter>`` out of a
 *  macro's inner content. Confluence wraps language hints, expand titles,
 *  Jira keys, status labels, etc. in these. Returns "" when absent. */
function extractParam(inner: string, name: string): string {
  const re = new RegExp(
    `<ac:parameter\\b[^>]*\\bac:name="${name}"[^>]*>([\\s\\S]*?)</ac:parameter>`,
    "i",
  );
  const m = re.exec(inner);
  return m ? m[1].trim() : "";
}

/** Body text for ``code`` macros. Confluence wraps the payload in
 *  ``<ac:plain-text-body><![CDATA[...]]></ac:plain-text-body>``; HTML5
 *  treats CDATA as a bogus comment so we strip it ourselves. */
function extractPlainBody(inner: string): string {
  const m = /<ac:plain-text-body\b[^>]*>([\s\S]*?)<\/ac:plain-text-body>/i.exec(inner);
  if (!m) return "";
  return m[1].replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1");
}

/** Rich body for admonition / expand / panel macros — content is XHTML and
 *  is passed through unchanged so the surrounding markup keeps rendering.
 *  Falls back to the raw inner when no rich-text-body wrapper is present. */
function extractRichBody(inner: string): string {
  const m = /<ac:rich-text-body\b[^>]*>([\s\S]*?)<\/ac:rich-text-body>/i.exec(inner);
  return m ? m[1] : inner;
}

function convertMacro(name: string, inner: string): string {
  if (!name) return extractRichBody(inner);

  if (name === "code") {
    const lang = extractParam(inner, "language");
    const body = extractPlainBody(inner);
    const langAttr = lang ? ` class="language-${escapeAttr(lang)}"` : "";
    return `<pre><code${langAttr}>${escapeText(body)}</code></pre>`;
  }

  if (name in ADMONITION_EMOJI) {
    const body = extractRichBody(inner);
    return (
      `<div class="cf-admonition cf-admonition--${escapeAttr(name)}">` +
      `<span class="cf-admonition__icon" aria-hidden="true">${ADMONITION_EMOJI[name]}</span>` +
      `<div class="cf-admonition__body">${body}</div>` +
      `</div>`
    );
  }

  if (name === "expand") {
    const title = extractParam(inner, "title") || "Click to expand";
    const body = extractRichBody(inner);
    return (
      `<details class="cf-expand">` +
      `<summary>${escapeText(title)}</summary>` +
      `<div class="cf-expand__body">${body}</div>` +
      `</details>`
    );
  }

  if (name === "status") {
    const title = extractParam(inner, "title") || "";
    const colour = (
      extractParam(inner, "colour") || extractParam(inner, "color") || "grey"
    ).toLowerCase();
    if (!title) return "";
    return `<span class="cf-status cf-status--${escapeAttr(colour)}">${escapeText(title)}</span>`;
  }

  if (name === "jira") {
    const key = extractParam(inner, "key");
    if (key) return `<span class="cf-jira">${escapeText(key)}</span>`;
    const jql = extractParam(inner, "jqlQuery");
    if (jql) return `<span class="cf-jira" title="${escapeAttr(jql)}">JQL</span>`;
    return "";
  }

  if (DIAGRAM_MACROS.has(name)) {
    const filename =
      extractParam(inner, "diagramName") ||
      extractParam(inner, "name") ||
      extractParam(inner, "filename") ||
      "";
    const label = filename ? `${name} · ${filename}` : `${name} diagram`;
    return `<div class="cf-placeholder">${escapeText(label)}</div>`;
  }

  if (DYNAMIC_MACROS.has(name)) {
    return `<div class="cf-placeholder">[${escapeText(name)}]</div>`;
  }

  if (name === "panel" || name === "section" || name === "column" || name === "details") {
    // Container macros: unwrap and keep the body.
    return extractRichBody(inner);
  }

  // Unknown macro — keep the rich-text-body if present so we don't drop
  // any user content. Mirrors the BE markdownify converter's "transparent"
  // default in confluence/normalizer.py.
  return extractRichBody(inner);
}

/** Rewrite all ``<ac:structured-macro>`` blocks, iterating from innermost
 *  out so nested macros (e.g. an ``info`` inside an ``expand``) all resolve.
 *  The match pattern rejects any macro that *contains* another macro, which
 *  guarantees we replace the innermost first; the outer iteration then sees
 *  the (now plain-HTML) inner body. */
function rewriteStructuredMacros(html: string): string {
  const re =
    /<ac:structured-macro\b([^>]*)>((?:(?!<ac:structured-macro\b)[\s\S])*?)<\/ac:structured-macro>/gi;
  let prev: string;
  let out = html;
  let safety = 0;
  do {
    prev = out;
    out = out.replace(re, (_match, attrs, inner) => {
      const nameMatch = /\bac:name="([^"]+)"/i.exec(attrs);
      return convertMacro(nameMatch?.[1] ?? "", inner);
    });
    safety += 1;
  } while (prev !== out && safety < 20);
  return out;
}

/** Rewrite ``<ac:link>`` elements:
 *    - ``<ri:user .../>``     → magenta @mention chip.
 *    - ``<ri:page .../>``     → page-title pill (no link target — we don't
 *      have the destination doc id here, just the page's display title).
 *    - ``<ri:attachment .../>``→ drop (image macros already pulled the file). */
function rewriteAcLinks(html: string): string {
  return html.replace(
    /<ac:link\b[^>]*>([\s\S]*?)<\/ac:link>/gi,
    (_match, inner) => {
      const userTag = /<ri:user\b([^>]*)\/?>(?:<\/ri:user>)?/i.exec(inner);
      if (userTag) {
        const a = userTag[1];
        const display =
          /\bri:display-name="([^"]*)"/i.exec(a)?.[1] ||
          /\bri:username="([^"]*)"/i.exec(a)?.[1] ||
          /\bri:account-id="([^"]*)"/i.exec(a)?.[1] ||
          "user";
        return `<span class="cf-mention">@${escapeText(display)}</span>`;
      }
      const pageTag = /<ri:page\b([^>]*)\/?>(?:<\/ri:page>)?/i.exec(inner);
      if (pageTag) {
        const title = /\bri:content-title="([^"]*)"/i.exec(pageTag[1])?.[1] || "";
        const bodyText = inner
          .replace(/<ri:[^>]*\/?>(?:<\/ri:[^>]*>)?/gi, "")
          .replace(
            /<ac:plain-text-link-body\b[^>]*>([\s\S]*?)<\/ac:plain-text-link-body>/gi,
            "$1",
          )
          .replace(/<ac:link-body\b[^>]*>([\s\S]*?)<\/ac:link-body>/gi, "$1")
          .trim();
        const label = bodyText || title || "page";
        return `<span class="cf-pagelink" title="${escapeAttr(title)}">${escapeText(label)}</span>`;
      }
      if (/<ri:attachment\b/i.test(inner)) {
        return "";
      }
      // Body-only ac:link (e.g. plain URL link). Keep the body text.
      return inner
        .replace(/<ri:[^>]*\/?>(?:<\/ri:[^>]*>)?/gi, "")
        .replace(
          /<ac:plain-text-link-body\b[^>]*>([\s\S]*?)<\/ac:plain-text-link-body>/gi,
          "$1",
        )
        .replace(/<ac:link-body\b[^>]*>([\s\S]*?)<\/ac:link-body>/gi, "$1");
    },
  );
}

/** Convert ``<ac:emoticon ac:emoji-fallback="😄" .../>`` to the fallback
 *  character (Confluence already supplies a renderable unicode emoji on the
 *  element). Falls back to ``:shortname:`` text when no emoji is set. */
function rewriteEmoticons(html: string): string {
  return html.replace(/<ac:emoticon\b([^>]*)\/?>(?:<\/ac:emoticon>)?/gi, (_match, attrs) => {
    const fallback = /\bac:emoji-fallback="([^"]*)"/i.exec(attrs)?.[1];
    if (fallback) return escapeText(fallback);
    const short = /\bac:emoji-shortname="([^"]*)"/i.exec(attrs)?.[1];
    if (short) return escapeText(short);
    const name = /\bac:name="([^"]*)"/i.exec(attrs)?.[1];
    return name ? `:${escapeText(name)}:` : "";
  });
}

/** Layout wrappers carry no visual meaning at our scale (we don't reflow
 *  multi-column page layouts in the viewer pane), so unwrap them. */
function stripLayoutWrappers(html: string): string {
  return html
    .replace(/<\/?ac:layout\b[^>]*>/gi, "")
    .replace(/<\/?ac:layout-section\b[^>]*>/gi, "")
    .replace(/<\/?ac:layout-cell\b[^>]*>/gi, "");
}

// Drop stray Confluence-specific elements that survived more specific
// rewrites: placeholders, stray parameters, leftover CDATA, orphan ri:*
// references.
function stripStrayConfluenceTags(html: string): string {
  return html
    .replace(/<ac:placeholder\b[\s\S]*?<\/ac:placeholder>/gi, "")
    .replace(/<ac:parameter\b[\s\S]*?<\/ac:parameter>/gi, "")
    .replace(/<\/?ac:(?:rich-text-body|plain-text-body|plain-text-link-body|link-body|caption|adf-[\w-]+|inline-comment-marker|task-list|task-id|task-status|task-body|task)\b[^>]*>/gi, "")
    .replace(/<ri:[^>]*\/?>(?:<\/ri:[^>]*>)?/gi, "")
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1");
}

/** Rewrite Confluence-specific markup into renderable HTML. Image macros
 *  resolve attachment-relative filenames against the doc's attachment list;
 *  structured-macros, ac:link, ac:emoticon, and layout wrappers are handled
 *  by the helpers above. */
function rewriteConfluenceMarkup(html: string, attachments?: DocAttachment[]): string {
  let out = html;

  // 1. <ac:image …>…</ac:image> → <img>. Done first because images may
  //    legitimately appear inside structured-macros' rich bodies.
  out = out.replace(/<ac:image\b([^>]*)>([\s\S]*?)<\/ac:image>/gi, (_match, attrs, inner) => {
    const altAttr = /\bac:alt\s*=\s*"([^"]*)"/i.exec(attrs);
    const captionMatch = /<ac:caption[^>]*>([\s\S]*?)<\/ac:caption>/i.exec(inner);
    const filenameMatch = /\bri:filename\s*=\s*"([^"]*)"/i.exec(inner);
    const urlMatch = /\bri:value\s*=\s*"([^"]*)"/i.exec(inner);
    const rawSrc = filenameMatch?.[1] ?? urlMatch?.[1] ?? "";
    const resolved = resolveImageSrc(rawSrc, attachments);
    const alt =
      altAttr?.[1] ?? (captionMatch ? captionMatch[1].replace(/<[^>]+>/g, "").trim() : "");
    if (!resolved) {
      return `<span class="cf-image-missing">[image: ${escapeAttr(alt || rawSrc || "missing")}]</span>`;
    }
    return `<img src="${escapeAttr(resolved)}" alt="${escapeAttr(alt)}" loading="lazy" />`;
  });

  // 2. ac:structured-macro (code / info / note / warning / tip / expand /
  //    status / jira / panel / drawio / dynamic).
  out = rewriteStructuredMacros(out);

  // 3. ac:link → user / page / drop attachment.
  out = rewriteAcLinks(out);

  // 4. ac:emoticon → unicode emoji.
  out = rewriteEmoticons(out);

  // 5. Layout wrappers — unwrap (single-column display).
  out = stripLayoutWrappers(out);

  // 6. Stray ri:attachment / ac:placeholder / ac:parameter / CDATA.
  out = stripStrayConfluenceTags(out);

  // 7. Bare <img src="filename.png"> — resolve filename-only refs against
  //    the attachment list. Leaves absolute / root-relative srcs alone.
  out = out.replace(/<img\b([^>]*?)\s+src\s*=\s*"([^"]+)"([^>]*)>/gi, (match, before, src, after) => {
    const resolved = resolveImageSrc(src, attachments);
    if (!resolved) return match;
    if (resolved === src) return match;
    return `<img${before} src="${escapeAttr(resolved)}"${after}>`;
  });

  return out;
}

export function HtmlRender({
  html,
  attachments,
}: {
  html: string;
  attachments?: DocAttachment[];
}) {
  const clean = useMemo(
    () => sanitizeHtml(rewriteConfluenceMarkup(html, attachments)),
    [html, attachments],
  );
  return (
    <div
      className="doc-viewer-html font-serif text-[15px] text-ink leading-relaxed"
      // Self-owned content from the user's own Confluence; sanitized above.
      dangerouslySetInnerHTML={{ __html: clean }}
    />
  );
}
