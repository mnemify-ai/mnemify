// The single style source for rendered prose.
//
// Three renderers put text on screen — the document viewer's markdown parser,
// its Notion-block walker, and the assistant's chat markdown — and each used
// to carry its own copy of every class string. They stay three *parsers*
// (their inputs have nothing in common), but there is exactly one place that
// decides what a code block, a link, a table cell or a checked task looks
// like: here.
//
// Two divergences are deliberate, not drift, and are modelled as variants:
//   • scale — documents are a reading surface (text-2xl headings, roomy
//     spacing); chat answers sit in a narrow dock and run tighter.
//   • inline code — the doc surface tints with `bone`, chat tints with an
//     ink alpha so the chip stays legible against the bubble in both themes.

/** `doc` = document viewer (reading surface). `chat` = assistant answers. */
export type ProseVariant = "doc" | "chat";

// ── containers ──────────────────────────────────────────────────────

export const proseArticleCls =
  "font-serif text-[15px] text-ink leading-relaxed space-y-3";

/** Chat answers stack tighter — the dock is narrow and turns are short. */
export const chatProseCls = "space-y-1.5";

// ── block elements ──────────────────────────────────────────────────

export const codeBlockCls =
  "font-mono text-[12px] text-ink/90 bg-bone/40 border border-hair rounded-lg p-3 overflow-x-auto";

/** Raw/unparseable payload dumps — same shell, wrapping instead of scrolling. */
export const rawBlockCls =
  "font-mono text-[11px] text-ink/90 whitespace-pre-wrap break-words bg-bone/40 border border-hair rounded-lg p-3";

export const blockquoteCls =
  "border-l-2 border-magenta/40 pl-4 italic text-muted";

export const hrCls = "border-t border-hair my-3";

export const paragraphCls = "text-ink";

/** A quiet inset block: callout shells, attachment placeholders, link cards. */
export const insetCls = "px-3 py-2 rounded-md bg-bone/30 border border-hair";

// ── inline elements ─────────────────────────────────────────────────

export const linkCls = "text-magenta hover:underline";

export const strongCls = "font-semibold";
export const emphasisCls = "italic";
export const strikeCls = "text-muted";

export function inlineCodeCls(variant: ProseVariant = "doc"): string {
  return variant === "chat"
    ? "rounded bg-ink/[0.06] px-1 py-0.5 font-mono text-[12px]"
    : "font-mono text-[12px] bg-bone/60 px-1 py-0.5 rounded";
}

// ── lists ───────────────────────────────────────────────────────────

export const listCls = "space-y-1";
export const bulletItemCls = "ml-5 list-disc";
export const orderedItemCls = "ml-5 list-decimal";

/** Chat lists indent via padding on the list itself, not margin per item. */
export const chatListCls = "pl-4 space-y-0.5";

// ── tables ──────────────────────────────────────────────────────────

/** Wide tables scroll inside themselves rather than widening the page. */
export const tableWrapCls = "overflow-x-auto -mx-1 px-1";
export const tableCls = "border-collapse text-sm w-full";
export const theadRowCls = "border-b border-hair";
export const thCls =
  "text-left font-sans text-[11px] uppercase tracking-eyebrow text-muted px-2 py-1.5 align-bottom";
export const trCls = "border-b border-hair last:border-b-0 align-top";
export const tdCls = "px-2 py-1.5 text-ink/90";

// ── headings ────────────────────────────────────────────────────────

/** Markdown level (1-6) → classes. Documents keep a real type scale; chat
 *  answers compress to three visually distinct steps that never out-shout
 *  the surrounding UI. */
export function headingCls(level: number, variant: ProseVariant = "doc"): string {
  if (variant === "chat") {
    if (level <= 1) return "font-serif text-[15px] font-semibold text-ink mt-2 mb-0.5";
    if (level === 2) return "font-serif text-[13px] font-semibold text-ink mt-2 mb-0.5";
    return "font-sans text-[11px] font-medium uppercase tracking-wide text-muted mt-2 mb-0.5";
  }
  const size =
    level === 1
      ? "text-2xl font-semibold mt-2"
      : level === 2
        ? "text-xl font-semibold mt-2"
        : level === 3
          ? "text-lg font-semibold mt-1.5"
          : "text-base font-semibold mt-1";
  return `${size} text-ink leading-tight`;
}

/** Heading tag for a markdown level. Document renderers start at `h2` — the
 *  page's own `h1` is the document title, so a `#` inside the body must not
 *  compete with it. Chat answers start lower still: a turn is nested inside
 *  the dock's own heading structure. */
export function headingTag(
  level: number,
  variant: ProseVariant = "doc",
): "h2" | "h3" | "h4" | "h5" | "h6" {
  const base = variant === "chat" ? 3 : 1;
  const tag = Math.min(base + Math.max(level, 1), 6);
  return `h${tag}` as "h2" | "h3" | "h4" | "h5" | "h6";
}
