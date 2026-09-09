import { useMemo, useState, type ReactNode } from "react";
import { Badge, type BadgeProps } from "../app/components/ui/Badge";
import { Pill, type PillProps } from "../app/components/ui/Pill";
import {
  chatListCls,
  chatProseCls,
  emphasisCls,
  headingCls,
  headingTag,
  InlineCode,
  strongCls,
} from "../app/components/markdown";
import { cn } from "../app/lib/cn";
import { CitationChip } from "./CitationChip";
import type { TerrainFocusTarget } from "./citationDisplay";
import type { SourceInspectorTarget } from "./SourceInspector";
import type { Citation } from "./types";

type CitationActions = {
  onFocusTerrain?: (target: TerrainFocusTarget) => void;
  onViewSource?: (target: SourceInspectorTarget) => void;
};

/**
 * Restrained Markdown + citation renderer for assistant chat answers.
 * Dependency-free, scoped to what LLM chat prose actually needs — headings,
 * bold/italic/code, lists, paragraphs, and inline `[cN]` citation markers
 * grouped into compact "N sources" controls. No tables/images/footnotes
 * (see DocViewerMarkdown.tsx for the document-viewer's fuller parser).
 */
export function AssistantMarkdown({
  text,
  citations,
  onFocusTerrain,
  onViewSource,
}: {
  text: string;
  citations: Citation[];
} & CitationActions) {
  const blocks = useMemo(() => parseBlocks(text), [text]);
  const actions: CitationActions = { onFocusTerrain, onViewSource };
  return (
    <div className={chatProseCls}>
      {blocks.map((block, i) => (
        <Block key={i} block={block} citations={citations} actions={actions} />
      ))}
    </div>
  );
}

// ── block model ─────────────────────────────────────────────────────

type BlockNode =
  | { type: "heading"; level: 1 | 2 | 3; text: string }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "p"; text: string };

function parseBlocks(src: string): BlockNode[] {
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const blocks: BlockNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      const level = Math.min(heading[1].length, 3) as 1 | 2 | 3;
      blocks.push({ type: "heading", level, text: heading[2].trim() });
      i += 1;
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*]\s+/, "").trim());
        i += 1;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s+/, "").trim());
        i += 1;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    // Paragraph: consume lines until a blank line or the start of another
    // block type. Soft-wrapped lines join with a space, matching normal
    // Markdown paragraph behavior.
    const buf: string[] = [line.trim()];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,6})\s+/.test(lines[i]) &&
      !/^[-*]\s+/.test(lines[i]) &&
      !/^\d+\.\s+/.test(lines[i])
    ) {
      buf.push(lines[i].trim());
      i += 1;
    }
    blocks.push({ type: "p", text: buf.join(" ") });
  }

  return blocks;
}

function Block({
  block,
  citations,
  actions,
}: {
  block: BlockNode;
  citations: Citation[];
  actions: CitationActions;
}) {
  if (block.type === "heading") {
    const Tag = headingTag(block.level, "chat");
    return (
      <Tag className={headingCls(block.level, "chat")}>
        {renderInline(block.text, citations, actions)}
      </Tag>
    );
  }

  if (block.type === "ul" || block.type === "ol") {
    const ListTag = block.type === "ul" ? "ul" : "ol";
    return (
      <ListTag
        className={cn(chatListCls, block.type === "ul" ? "list-disc" : "list-decimal")}
      >
        {block.items.map((item, i) => (
          <li key={i}>
            <BlockBody text={item} citations={citations} actions={actions} />
          </li>
        ))}
      </ListTag>
    );
  }

  return (
    <p className="leading-relaxed">
      <BlockBody text={block.text} citations={citations} actions={actions} />
    </p>
  );
}

/** Paragraph/list-item body: strips + badges a leading semantic label
 *  ("Blocked:", "Risk:", …) if present, then renders the remaining text
 *  inline. Prose that doesn't start with one of these words is untouched. */
function BlockBody({
  text,
  citations,
  actions,
}: {
  text: string;
  citations: Citation[];
  actions: CitationActions;
}) {
  const detected = detectLeadingLabel(text);
  if (!detected) return <>{renderInline(text, citations, actions)}</>;

  const { style, rest } = detected;
  const badge =
    style.comp === "badge" ? (
      <Badge tone={style.tone} className="mr-1.5 align-middle">
        {style.display}
      </Badge>
    ) : (
      <Pill tone={style.tone} dot={style.dot} className="mr-1.5 inline-flex align-middle py-0.5 px-2">
        {style.display}
      </Pill>
    );

  if (!rest.trim()) return badge;
  return (
    <>
      {badge}
      {renderInline(rest, citations, actions)}
    </>
  );
}

// ── badge/label heuristic ───────────────────────────────────────────

const LEADING_LABEL_RE =
  /^(?:\*\*)?\s*(blocked|risks?|open questions?|todo|next steps?|action items?|decisions?|decided|done|completed|resolved|in progress)\s*:?(?:\*\*)?\s*/i;

type LabelStyle =
  | { comp: "badge"; tone: BadgeProps["tone"]; display: string }
  | { comp: "pill"; tone: PillProps["tone"]; dot?: boolean; display: string };

const LABEL_STYLE: Record<string, LabelStyle> = {
  blocked: { comp: "pill", tone: "danger", display: "Blocked" },
  risk: { comp: "pill", tone: "warning", display: "Risk" },
  risks: { comp: "pill", tone: "warning", display: "Risk" },
  "open question": { comp: "pill", tone: "info", display: "Open Question" },
  "open questions": { comp: "pill", tone: "info", display: "Open Questions" },
  todo: { comp: "badge", tone: "magenta", display: "To Do" },
  "next step": { comp: "badge", tone: "magenta", display: "Next Step" },
  "next steps": { comp: "badge", tone: "magenta", display: "Next Steps" },
  "action item": { comp: "badge", tone: "magenta", display: "Action Item" },
  "action items": { comp: "badge", tone: "magenta", display: "Action Items" },
  decision: { comp: "badge", tone: "sage", display: "Decision" },
  decisions: { comp: "badge", tone: "sage", display: "Decisions" },
  decided: { comp: "badge", tone: "sage", display: "Decided" },
  done: { comp: "pill", tone: "success", display: "Done" },
  completed: { comp: "pill", tone: "success", display: "Completed" },
  resolved: { comp: "pill", tone: "success", display: "Resolved" },
  "in progress": { comp: "pill", tone: "neutral", dot: true, display: "In Progress" },
};

function detectLeadingLabel(text: string): { style: LabelStyle; rest: string } | null {
  const m = LEADING_LABEL_RE.exec(text);
  if (!m) return null;
  const style = LABEL_STYLE[m[1].toLowerCase()];
  if (!style) return null;
  return { style, rest: text.slice(m[0].length) };
}

// ── inline tokenizer ────────────────────────────────────────────────

const INLINE_RE =
  /(\*\*.+?\*\*|\*[^*\n]+\*|_[^_\n]+_|`[^`\n]+`|\[c\d+\](?:[,;]?\s*\[c\d+\])*)/g;

type InlineToken =
  | { type: "text"; text: string }
  | { type: "bold"; text: string }
  | { type: "italic"; text: string }
  | { type: "code"; text: string }
  | { type: "citations"; ids: string[] };

function tokenizeInline(text: string): InlineToken[] {
  const tokens: InlineToken[] = [];
  let last = 0;
  for (const m of text.matchAll(INLINE_RE)) {
    const idx = m.index ?? 0;
    if (idx > last) tokens.push({ type: "text", text: text.slice(last, idx) });
    const raw = m[0];
    if (raw.startsWith("**")) {
      tokens.push({ type: "bold", text: raw.slice(2, -2) });
    } else if (raw.startsWith("`")) {
      tokens.push({ type: "code", text: raw.slice(1, -1) });
    } else if (raw.startsWith("[c")) {
      const ids = Array.from(raw.matchAll(/c\d+/g)).map((x) => x[0]);
      tokens.push({ type: "citations", ids });
    } else {
      tokens.push({ type: "italic", text: raw.slice(1, -1) });
    }
    last = idx + raw.length;
  }
  if (last < text.length) tokens.push({ type: "text", text: text.slice(last) });
  return tokens;
}

function renderInline(
  text: string,
  citations: Citation[],
  actions: CitationActions,
): ReactNode[] {
  const tokens = tokenizeInline(text);
  return tokens.map((token, i) => {
    switch (token.type) {
      case "bold":
        return (
          <strong key={i} className={cn(strongCls, "text-ink")}>
            {token.text}
          </strong>
        );
      case "italic":
        return (
          <em key={i} className={emphasisCls}>
            {token.text}
          </em>
        );
      case "code":
        return (
          <InlineCode key={i} variant="chat">
            {token.text}
          </InlineCode>
        );
      case "citations":
        return (
          <CitationGroup
            key={i}
            ids={token.ids}
            citations={citations}
            actions={actions}
          />
        );
      default:
        return <span key={i}>{token.text}</span>;
    }
  });
}

// ── inline citation groups ──────────────────────────────────────────

/**
 * Consecutive `[cN]` markers backing one claim collapse to the first chip +
 * a compact "+N" chip. Clicking "+N" expands the remaining chips inline (in
 * the original marker order — the answer's ranking); a "−" chip collapses
 * them back. Every expanded chip is a full CitationChip with its own hover
 * preview and click popover.
 */
function CitationGroup({
  ids,
  citations,
  actions,
}: {
  ids: string[];
  citations: Citation[];
  actions: CitationActions;
}) {
  const [expanded, setExpanded] = useState(false);
  const byId = new Map(citations.map((c) => [c.citation_id, c]));
  const resolved = ids.map((id) => byId.get(id)).filter((c): c is Citation => Boolean(c));

  if (resolved.length === 0) return null; // hallucinated marker, no matching citation
  if (resolved.length === 1) {
    return (
      <CitationChip
        citation={resolved[0]}
        onFocusTerrain={actions.onFocusTerrain}
        onViewSource={actions.onViewSource}
      />
    );
  }

  const shown = expanded ? resolved : resolved.slice(0, 1);
  const hidden = resolved.length - 1;

  return (
    <span className="inline-flex flex-wrap items-center gap-1 align-baseline">
      {shown.map((c) => (
        <CitationChip
          key={c.citation_id}
          citation={c}
          onFocusTerrain={actions.onFocusTerrain}
          onViewSource={actions.onViewSource}
        />
      ))}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-label={
          expanded
            ? "Collapse sources"
            : `Show ${hidden} more source${hidden > 1 ? "s" : ""}`
        }
        className={cn(
          "inline-flex items-center rounded-full border border-hair bg-cream px-1.5 py-0.5",
          "font-sans text-[11px] tabular-nums text-muted hover:text-ink hover:bg-ink/5 transition-colors",
        )}
      >
        {expanded ? "−" : `+${hidden}`}
      </button>
    </span>
  );
}
