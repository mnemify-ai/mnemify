// Shared prose primitives — the pieces every renderer draws identically.
//
// Only markup that was genuinely duplicated lives here (the task checkbox and
// the table shell were byte-for-byte copies in DocViewerMarkdown and
// DocViewerNotion). Anything a renderer does uniquely stays in that renderer
// and reaches for `tokens.ts` instead.

import type { ReactNode } from "react";
import { cn } from "../../lib/cn";
import {
  blockquoteCls,
  codeBlockCls,
  hrCls,
  inlineCodeCls,
  linkCls,
  proseArticleCls,
  rawBlockCls,
  tableCls,
  tableWrapCls,
  tdCls,
  theadRowCls,
  thCls,
  trCls,
  type ProseVariant,
} from "./tokens";

/** The reading-surface wrapper both document renderers emit. */
export function ProseArticle({ children }: { children: ReactNode }) {
  return <article className={proseArticleCls}>{children}</article>;
}

export function CodeBlock({ children, lang }: { children: string; lang?: string }) {
  return (
    <pre className={codeBlockCls}>
      <code>{children}</code>
      {lang ? <span className="sr-only">language: {lang}</span> : null}
    </pre>
  );
}

/** Unparseable payload shown verbatim rather than swallowed. */
export function RawBlock({ content }: { content: string }) {
  return <pre className={rawBlockCls}>{content}</pre>;
}

export function InlineCode({
  children,
  variant = "doc",
}: {
  children: ReactNode;
  variant?: ProseVariant;
}) {
  return <code className={inlineCodeCls(variant)}>{children}</code>;
}

/** Every prose link leaves the app, so they all carry the same rel/target. */
export function ProseLink({
  href,
  children,
  className,
}: {
  href: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className={cn(linkCls, className)}>
      {children}
    </a>
  );
}

export function Blockquote({ children }: { children: ReactNode }) {
  return <blockquote className={blockquoteCls}>{children}</blockquote>;
}

export function ProseHr() {
  return <hr className={hrCls} />;
}

/** Table shell — the horizontal-scroll wrapper plus the `<table>`. Callers
 *  supply their own head/body because their cell content differs (parsed
 *  markdown vs. Notion property values). */
export function ProseTable({ children }: { children: ReactNode }) {
  return (
    <div className={tableWrapCls}>
      <table className={tableCls}>{children}</table>
    </div>
  );
}

export function ProseTh({ children }: { children: ReactNode }) {
  return <th className={thCls}>{children}</th>;
}

export function ProseTr({ children }: { children: ReactNode }) {
  return <tr className={trCls}>{children}</tr>;
}

export function ProseTheadRow({ children }: { children: ReactNode }) {
  return <tr className={theadRowCls}>{children}</tr>;
}

export function ProseTd({ children, className }: { children: ReactNode; className?: string }) {
  return <td className={cn(tdCls, className)}>{children}</td>;
}

/**
 * Task-list checkbox. Markdown `- [x]` and Notion `to_do` blocks both land
 * here, so a checked task looks the same whichever source it came from.
 * Presentational only — `aria-hidden`, because the accessible state is
 * carried by the surrounding label/list-item text.
 */
export function TaskCheckbox({ checked }: { checked: boolean }) {
  return (
    <span
      className={cn(
        "h-4 w-4 mt-1 rounded border flex items-center justify-center shrink-0",
        checked ? "bg-magenta border-magenta text-cream" : "border-line/30 bg-cream",
      )}
      aria-hidden
    >
      {checked && (
        <svg viewBox="0 0 12 12" className="w-2.5 h-2.5">
          <path
            d="M2.5 6.5L5 9L9.5 3.5"
            stroke="currentColor"
            strokeWidth="2"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </span>
  );
}

/** Struck-through, muted body text for a completed task. */
export function TaskLabel({ checked, children }: { checked: boolean; children: ReactNode }) {
  return <span className={checked ? "line-through text-muted" : ""}>{children}</span>;
}
