// Markdown renderer for the document viewer. A tight, dependency-free parser
// covering the common 80% of inline + block syntax: headings, bold/italic,
// inline code, fenced code blocks, links, lists, blockquotes, paragraphs,
// images (with attachment-name resolution for Confluence-style filenames),
// plus Obsidian-flavoured extensions: YAML frontmatter strip, callouts
// (`> [!info]`), tables, task-list checkboxes, `==highlights==`,
// `~~strikethrough~~`, `---` horizontal rule, `![[wikilink]]` image embeds,
// `#tags`, and footnote markers.
//
// Extracted from DocViewerPane.tsx — markdown is ~300 lines and stands on
// its own. NotionRender re-uses MarkdownRender via re-export so the
// pre-baked-markdown fallback path stays cheap.

import { useMemo } from "react";
import { apiUrl } from "../api/client";
import type { DocAttachment } from "../api/documents";
import {
  Blockquote,
  bulletItemCls,
  CodeBlock,
  headingCls,
  headingTag,
  InlineCode,
  listCls,
  orderedItemCls,
  paragraphCls,
  ProseArticle,
  ProseHr,
  ProseLink,
  ProseTable,
  ProseTd,
  ProseTh,
  ProseTheadRow,
  ProseTr,
  emphasisCls,
  strikeCls,
  strongCls,
  TaskCheckbox,
  TaskLabel,
} from "./markdown";

const IMAGE_EXTENSIONS = new Set([
  "png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "avif", "ico",
]);

const CALLOUT_KINDS: Record<
  string,
  { emoji: string; tone: "default" | "info" | "warn" | "tip" | "danger" | "quote" }
> = {
  note: { emoji: "📝", tone: "default" },
  abstract: { emoji: "📚", tone: "info" },
  summary: { emoji: "📚", tone: "info" },
  tldr: { emoji: "📚", tone: "info" },
  info: { emoji: "ℹ️", tone: "info" },
  todo: { emoji: "✅", tone: "info" },
  tip: { emoji: "💡", tone: "tip" },
  hint: { emoji: "💡", tone: "tip" },
  important: { emoji: "❗", tone: "warn" },
  success: { emoji: "✅", tone: "tip" },
  check: { emoji: "✅", tone: "tip" },
  done: { emoji: "✅", tone: "tip" },
  question: { emoji: "❓", tone: "info" },
  help: { emoji: "❓", tone: "info" },
  faq: { emoji: "❓", tone: "info" },
  warning: { emoji: "⚠️", tone: "warn" },
  caution: { emoji: "⚠️", tone: "warn" },
  attention: { emoji: "⚠️", tone: "warn" },
  failure: { emoji: "❌", tone: "danger" },
  fail: { emoji: "❌", tone: "danger" },
  missing: { emoji: "❌", tone: "danger" },
  danger: { emoji: "🔥", tone: "danger" },
  error: { emoji: "🔥", tone: "danger" },
  bug: { emoji: "🐛", tone: "danger" },
  example: { emoji: "📋", tone: "default" },
  quote: { emoji: "💬", tone: "quote" },
  cite: { emoji: "💬", tone: "quote" },
};

const CALLOUT_TONE_CLASSES: Record<string, string> = {
  default: "border-hair bg-bone/40",
  info: "border-[rgb(91_156_255/0.25)] bg-[rgb(91_156_255/0.06)]",
  warn: "border-[rgb(255_178_91/0.30)] bg-[rgb(255_178_91/0.08)]",
  tip: "border-[rgb(91_200_140/0.28)] bg-[rgb(91_200_140/0.08)]",
  danger: "border-[rgb(255_100_100/0.30)] bg-[rgb(255_100_100/0.08)]",
  quote: "border-magenta/30 bg-bone/30",
};

/** Strip a YAML frontmatter block (``---\n…\n---``) off the top of the
 *  document. Obsidian raw notes include this verbatim and the BE
 *  normalizer is a pass-through for Obsidian, so without this strip every
 *  note opens with a block of literal ``title: ...\ntags: …`` text. */
function stripFrontmatter(src: string): string {
  const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(src);
  return m ? src.slice(m[0].length) : src;
}

/** A tight markdown renderer covering the common 80%, plus Obsidian quirks.
 *  Returns a single <article>. */
export function MarkdownRender({
  source,
  attachments,
}: {
  source: string;
  attachments?: DocAttachment[];
}) {
  const blocks = useMemo(
    () => parseMarkdown(stripFrontmatter(source), attachments),
    [source, attachments],
  );
  return <ProseArticle>{blocks}</ProseArticle>;
}

function parseMarkdown(src: string, attachments?: DocAttachment[]): React.ReactNode[] {
  const lines = src.split(/\r?\n/);
  const out: React.ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    if (/^```/.test(line)) {
      const lang = line.replace(/^```/, "").trim();
      const buf: string[] = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i])) {
        buf.push(lines[i]);
        i += 1;
      }
      i += 1; // skip closing fence
      out.push(
        <CodeBlock key={key++} lang={lang || undefined}>
          {buf.join("\n")}
        </CodeBlock>,
      );
      continue;
    }

    // Horizontal rule (must come before list/paragraph; uses 3+ of -, _, or *).
    if (/^\s*(?:-{3,}|_{3,}|\*{3,})\s*$/.test(line)) {
      out.push(<ProseHr key={key++} />);
      i += 1;
      continue;
    }

    // Heading
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      const Tag = headingTag(level);
      out.push(
        <Tag key={key++} className={headingCls(level)}>
          {renderInline(h[2], attachments)}
        </Tag>,
      );
      i += 1;
      continue;
    }

    // Table — header row + |---|---| separator + body rows.
    if (
      isTableRowLine(line) &&
      i + 1 < lines.length &&
      /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1]) &&
      /---/.test(lines[i + 1])
    ) {
      const headers = splitTableRow(line);
      i += 2; // skip header + separator
      const rows: string[][] = [];
      while (i < lines.length && isTableRowLine(lines[i])) {
        rows.push(splitTableRow(lines[i]));
        i += 1;
      }
      out.push(
        <ProseTable key={key++}>
          <thead>
            <ProseTheadRow>
              {headers.map((h, hi) => (
                <ProseTh key={hi}>{renderInline(h, attachments)}</ProseTh>
              ))}
            </ProseTheadRow>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <ProseTr key={ri}>
                {row.map((cell, ci) => (
                  <ProseTd key={ci}>{renderInline(cell, attachments)}</ProseTd>
                ))}
              </ProseTr>
            ))}
          </tbody>
        </ProseTable>,
      );
      continue;
    }

    // Unordered list (with optional task checkbox)
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: React.ReactNode[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        const rawText = lines[i].replace(/^\s*[-*+]\s+/, "");
        const task = /^\[([ xX/-])\]\s+(.*)$/.exec(rawText);
        if (task) {
          const checked = task[1].toLowerCase() === "x";
          items.push(
            <li key={key++} className="ml-1 list-none flex items-start gap-2 -indent-0">
              <TaskCheckbox checked={checked} />
              <TaskLabel checked={checked}>
                {renderInline(task[2], attachments)}
              </TaskLabel>
            </li>,
          );
        } else {
          items.push(
            <li key={key++} className={bulletItemCls}>
              {renderInline(rawText, attachments)}
            </li>,
          );
        }
        i += 1;
      }
      out.push(
        <ul key={key++} className={listCls}>
          {items}
        </ul>,
      );
      continue;
    }

    // Ordered list
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: React.ReactNode[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        const text = lines[i].replace(/^\s*\d+\.\s+/, "");
        items.push(
          <li key={key++} className={orderedItemCls}>
            {renderInline(text, attachments)}
          </li>,
        );
        i += 1;
      }
      out.push(
        <ol key={key++} className={listCls}>
          {items}
        </ol>,
      );
      continue;
    }

    // Blockquote / callout (Obsidian: `> [!info] Optional title`)
    if (/^>\s?/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^>\s?/, ""));
        i += 1;
      }
      const callout = /^\[!(\w+)\][+-]?\s*(.*)$/.exec(buf[0] || "");
      if (callout) {
        const kindName = callout[1].toLowerCase();
        const kind = CALLOUT_KINDS[kindName] || { emoji: "📝", tone: "default" as const };
        const title = callout[2].trim() || capitalize(kindName);
        const bodySrc = buf.slice(1).join("\n").trim();
        const bodyNodes = bodySrc
          ? parseMarkdown(bodySrc, attachments)
          : null;
        const toneClass =
          CALLOUT_TONE_CLASSES[kind.tone] ?? CALLOUT_TONE_CLASSES.default;
        out.push(
          <div
            key={key++}
            className={`flex gap-3 rounded-lg border px-3.5 py-2.5 ${toneClass}`}
          >
            <span className="text-base leading-snug mt-0.5 shrink-0" aria-hidden>
              {kind.emoji}
            </span>
            <div className="flex-1 min-w-0">
              <p className="font-sans text-[13px] font-medium text-ink mb-1 leading-snug">
                {title}
              </p>
              {bodyNodes && (
                <div className="space-y-2 text-[14px]">{bodyNodes}</div>
              )}
            </div>
          </div>,
        );
        continue;
      }
      out.push(
        <Blockquote key={key++}>
          {renderInline(buf.join(" "), attachments)}
        </Blockquote>,
      );
      continue;
    }

    // Blank line — paragraph break
    if (line.trim() === "") {
      i += 1;
      continue;
    }

    // Paragraph (consume contiguous non-blank lines)
    const buf: string[] = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^(#{1,6})\s+/.test(lines[i]) &&
      !/^\s*[-*+]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !/^```/.test(lines[i]) &&
      !/^>\s?/.test(lines[i]) &&
      !/^\s*(?:-{3,}|_{3,}|\*{3,})\s*$/.test(lines[i]) &&
      !isTableRowLine(lines[i])
    ) {
      buf.push(lines[i]);
      i += 1;
    }
    out.push(
      <p key={key++} className={paragraphCls}>
        {renderInline(buf.join(" "), attachments)}
      </p>,
    );
  }

  return out;
}

function isTableRowLine(line: string): boolean {
  if (!line.includes("|")) return false;
  const trimmed = line.trim();
  return trimmed.startsWith("|") && trimmed.endsWith("|") && trimmed.length > 2;
}

function splitTableRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map((c) => c.trim());
}

function capitalize(s: string): string {
  if (!s) return "";
  return s[0].toUpperCase() + s.slice(1);
}

/** Resolve a markdown image ``src`` to a usable URL.
 *
 *  Absolute URLs (http/https) and root-absolute paths (``/api/...``) are
 *  used as-is. Anything else is treated as a Confluence-style filename and
 *  looked up against the document's attachment list (matched on the
 *  original filename, which the BE surfaces via ``DocAttachment.name``).
 *  Returns ``null`` when the lookup fails — the caller renders a small
 *  text placeholder instead of a broken <img>. */
function resolveImageSrc(src: string, attachments?: DocAttachment[]): string | null {
  if (
    src.startsWith("http://") ||
    src.startsWith("https://") ||
    src.startsWith("data:") ||
    src.startsWith("/")
  ) {
    return src;
  }
  const hit = attachments?.find((a) => a.name === src);
  return hit ? hit.url : null;
}

/** Inline markdown: **bold**, *italic*, `code`, [text](url), [[wikilinks]],
 *  ![alt](src) images, plus Obsidian: ![[file]] image embeds, ==highlight==,
 *  ~~strikethrough~~, #tag, [^footnote]. */
function renderInline(text: string, attachments?: DocAttachment[]): React.ReactNode[] {
  // Tokenize step-by-step.
  const out: React.ReactNode[] = [];
  let rest = text;
  let key = 0;

  // Order matters: code first (prevents inner ** parsing), then images
  // (both ![alt](src) and ![[ref]] wikilink-style), then wikilinks, then
  // links, then bold, italic, strikethrough, highlight, tags, footnotes.
  const patterns: { re: RegExp; render: (m: RegExpExecArray) => React.ReactNode }[] = [
    {
      re: /`([^`]+)`/,
      render: (m) => <InlineCode key={key++}>{m[1]}</InlineCode>,
    },
    {
      re: /!\[\[([^\]|]+)(?:\|([^\]]*))?\]\]/,
      render: (m) => {
        const ref = m[1].trim();
        const alias = m[2]?.trim() || ref;
        const ext = ref.split(".").pop()?.toLowerCase() ?? "";
        if (IMAGE_EXTENSIONS.has(ext)) {
          const resolved = resolveImageSrc(ref, attachments);
          if (resolved) {
            return (
              <img
                key={key++}
                src={apiUrl(resolved)}
                alt={alias}
                className="max-w-full h-auto rounded-md border border-hair my-2 inline-block"
                loading="lazy"
              />
            );
          }
          return (
            <span
              key={key++}
              className="font-sans text-xs text-muted italic"
              title={`Missing attachment: ${ref}`}
            >
              [image: {alias}]
            </span>
          );
        }
        // Non-image wikilink embed (note transclusion). We don't pull the
        // target's body here — surface the reference as a styled badge.
        return (
          <span
            key={key++}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-hair bg-bone/30 text-[12px] font-sans text-muted"
            title={`Embed: ${ref}`}
          >
            ↪ {alias}
          </span>
        );
      },
    },
    {
      re: /!\[([^\]]*)\]\(([^)]+)\)/,
      render: (m) => {
        const alt = m[1] || "";
        const resolved = resolveImageSrc(m[2], attachments);
        if (!resolved) {
          return (
            <span
              key={key++}
              className="font-sans text-xs text-muted italic"
              title={`Missing attachment: ${m[2]}`}
            >
              [image: {alt || m[2]}]
            </span>
          );
        }
        return (
          <img
            key={key++}
            src={apiUrl(resolved)}
            alt={alt}
            className="max-w-full h-auto rounded-md border border-hair my-2 inline-block"
            loading="lazy"
          />
        );
      },
    },
    {
      re: /\[\[([^\]|]+)(?:\|([^\]]*))?\]\]/,
      render: (m) => (
        <span key={key++} className="text-magenta">
          {m[2]?.trim() || m[1].trim()}
        </span>
      ),
    },
    {
      re: /\[([^\]]+)\]\(([^)]+)\)/,
      render: (m) => (
        <ProseLink key={key++} href={m[2]}>
          {m[1]}
        </ProseLink>
      ),
    },
    {
      re: /\*\*([^*]+)\*\*/,
      render: (m) => (
        <strong key={key++} className={strongCls}>
          {m[1]}
        </strong>
      ),
    },
    {
      re: /~~([^~]+)~~/,
      render: (m) => (
        <s key={key++} className={strikeCls}>
          {m[1]}
        </s>
      ),
    },
    {
      re: /==([^=]+)==/,
      render: (m) => (
        <mark key={key++} className="bg-[rgb(255_220_91/0.40)] text-ink rounded px-0.5">
          {m[1]}
        </mark>
      ),
    },
    {
      re: /\*([^*]+)\*/,
      render: (m) => (
        <em key={key++} className={emphasisCls}>
          {m[1]}
        </em>
      ),
    },
    {
      // Obsidian inline tag. Word boundary on the left avoids matching the
      // ``#`` in ``#1`` (issue numbers) or inside URLs; the body must start
      // with a letter to skip ``#123``-style numeric anchors as well.
      re: /(?<![A-Za-z0-9/_])#([A-Za-z][\w/_-]*)/,
      render: (m) => (
        <span
          key={key++}
          className="inline-block font-sans text-[11px] text-magenta bg-magenta/10 rounded px-1.5 py-0.5 mx-0.5"
        >
          #{m[1]}
        </span>
      ),
    },
    {
      re: /\[\^([\w-]+)\]/,
      render: (m) => (
        <sup
          key={key++}
          className="text-[11px] text-magenta font-medium"
          title={`Footnote ${m[1]}`}
        >
          [{m[1]}]
        </sup>
      ),
    },
  ];

  while (rest.length > 0) {
    let earliest: { idx: number; match: RegExpExecArray; renderer: (m: RegExpExecArray) => React.ReactNode } | null = null;
    for (const pat of patterns) {
      const m = pat.re.exec(rest);
      if (m && (earliest === null || m.index < earliest.idx)) {
        earliest = { idx: m.index, match: m, renderer: pat.render };
      }
    }
    if (!earliest) {
      out.push(rest);
      break;
    }
    if (earliest.idx > 0) {
      out.push(rest.slice(0, earliest.idx));
    }
    out.push(earliest.renderer(earliest.match));
    rest = rest.slice(earliest.idx + earliest.match[0].length);
  }
  return out;
}
