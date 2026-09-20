/**
 * HTML sanitizer for content we render with `dangerouslySetInnerHTML`:
 * Confluence storage-format bodies (DocViewerHtml) and mammoth's DOCX
 * output (DocxRenderer).
 *
 * That content is written by whoever can edit the source page — i.e. not
 * necessarily the person running Mnemify — and it renders on the same
 * origin as `/api`. A single surviving `onerror=` or `<base href>` would
 * let a page author read every indexed document, rewrite API keys via
 * `/api/secrets`, or redirect the chat request that carries the BYOK key.
 * So: DOMPurify (a real HTML parser), not regexes.
 *
 * In a non-DOM environment (vitest's `node` environment) DOMPurify has no
 * `window`; we return an empty string rather than the unsanitized input.
 */
import DOMPurify from "dompurify";

const ALLOWED_URI = /^(?:https?:|mailto:|tel:|\/(?!\/)|#|data:image\/(?:png|jpe?g|gif|webp|avif);)/i;

let configured = false;
function configure(): void {
  if (configured) return;
  configured = true;
  DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName === "A") {
      // Harvested links open in a new tab and never get a `window.opener`.
      node.setAttribute("target", "_blank");
      node.setAttribute("rel", "noopener noreferrer");
    }
    // DOMPurify lets any `data:` URI through on media tags regardless of
    // ALLOWED_URI_REGEXP. Only inline *images* are wanted here.
    for (const attr of ["src", "href", "poster"]) {
      const v = node.getAttribute(attr);
      if (v && /^\s*data:/i.test(v) && !ALLOWED_URI.test(v.trim())) {
        node.removeAttribute(attr);
      }
    }
  });
}

export function sanitizeHtml(html: string): string {
  if (!DOMPurify.isSupported) return "";
  configure();
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    // Nothing that loads or submits on its own, changes URL resolution, or
    // embeds a separate scripting context. (`<img>`, `<details>`, `<pre>`,
    // `<table>`… the Confluence rewriter emits — all still allowed.)
    FORBID_TAGS: [
      "base", "link", "meta", "form", "input", "button", "textarea", "select",
      "style", "svg", "math", "iframe", "object", "embed", "template",
    ],
    ALLOW_DATA_ATTR: false,
    ALLOWED_URI_REGEXP: ALLOWED_URI,
  });
}
