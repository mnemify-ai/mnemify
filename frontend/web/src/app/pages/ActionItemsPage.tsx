import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  CalendarClock,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  ListTodo,
  Sparkles,
  X,
} from "lucide-react";
import { PageShell } from "../layouts/PageShell";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Pill } from "../components/ui/Pill";
import { Button } from "../components/ui/Button";
import { Skeleton } from "../components/ui/Skeleton";
import { useActionItems, type ActionItem } from "../api/actionItems";
import {
  cleanTitle,
  dueLabel,
  loadDismissed,
  partitionActionItems,
  pruneDismissed,
  saveDismissed,
} from "../lib/actionItems";
import { cn } from "../lib/cn";

type SectionKey = "overdue" | "dueSoon" | "upcoming" | "noDate";
type Tone = "danger" | "warning" | "info" | "neutral";

const SECTIONS: {
  key: SectionKey;
  title: string;
  blurb: string;
  tone: Tone;
  icon: typeof AlertTriangle;
  /** Start collapsed — for the long, low-signal tail. */
  collapsed?: boolean;
}[] = [
  {
    key: "overdue",
    title: "Overdue",
    blurb: "The stated deadline has passed",
    tone: "danger",
    icon: AlertTriangle,
  },
  {
    key: "dueSoon",
    title: "Due soon",
    blurb: "Due within the next 7 days",
    tone: "warning",
    icon: CalendarClock,
  },
  {
    key: "upcoming",
    title: "Upcoming",
    blurb: "Dated, but further out",
    tone: "info",
    icon: CalendarDays,
  },
  {
    key: "noDate",
    title: "No date",
    blurb: "Commitments without a stated deadline, most urgent first",
    tone: "neutral",
    icon: CircleDashed,
    collapsed: true,
  },
];

export function ActionItemsPage() {
  const navigate = useNavigate();
  const { data, isLoading } = useActionItems();
  const [dismissed, setDismissed] = useState<Set<string>>(() => loadDismissed());
  const [collapsed, setCollapsed] = useState<Set<SectionKey>>(
    () => new Set(SECTIONS.filter((s) => s.collapsed).map((s) => s.key)),
  );

  const parts = useMemo(
    () => (data ? partitionActionItems(data.items, dismissed) : null),
    [data, dismissed],
  );

  const dismiss = (id: string) => {
    setDismissed((prev) => {
      const next = new Set(prev);
      next.add(id);
      // Prune against the live list so removed/reworded items don't pile up.
      saveDismissed(data ? pruneDismissed(next, data.items) : next);
      return next;
    });
  };

  const toggle = (key: SectionKey) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const visibleTotal = parts
    ? parts.overdue.length + parts.dueSoon.length + parts.upcoming.length + parts.noDate.length
    : 0;
  // Every item undated → the map predates the deadline pipeline (or genuinely
  // nothing is dated); nudge a recompile rather than showing a silent wall.
  const needsRecompile =
    !!data && data.items.length > 0 && data.items.every((it) => !it.due_date && !it.due_text);

  return (
    <PageShell
      eyebrow="Commitments, surfaced"
      title="TODOs"
      description={
        "Deadlines and to-dos extracted from your documents at compile time, " +
        "re-checked against today whenever you look."
      }
      actions={
        parts ? (
          <div className="flex items-center gap-2">
            {parts.overdue.length > 0 && (
              <Pill tone="danger" dot>
                {parts.overdue.length} overdue
              </Pill>
            )}
            {parts.dueSoon.length > 0 && (
              <Pill tone="warning" dot>
                {parts.dueSoon.length} due soon
              </Pill>
            )}
            {parts.dismissedCount > 0 && (
              <span className="font-sans text-xs text-muted pl-1">
                {parts.dismissedCount} dismissed
              </span>
            )}
          </div>
        ) : undefined
      }
    >
      {isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-28 rounded-2xl" />
          <Skeleton className="h-28 rounded-2xl" />
        </div>
      ) : !data ? (
        <EmptyState
          icon={<ListTodo size={28} strokeWidth={1.5} />}
          title="No compiled map yet"
          description="Action items are extracted when your documents are compiled into the map. Run a compile first."
          action={<Button onClick={() => navigate("/build/compile")}>Go to Compile</Button>}
        />
      ) : visibleTotal === 0 ? (
        <EmptyState
          icon={<ListTodo size={28} strokeWidth={1.5} />}
          title="Nothing on your plate"
          description={
            parts!.dismissedCount > 0
              ? "Every extracted action item has been dismissed."
              : "No open to-dos were found in your compiled documents."
          }
        />
      ) : (
        <div className="space-y-5">
          {needsRecompile && (
            <div className="glass-panel rounded-2xl px-5 py-4 flex items-center gap-4">
              <Sparkles size={18} strokeWidth={1.75} className="text-magenta shrink-0" aria-hidden />
              <p className="font-sans text-sm text-ink leading-relaxed flex-1">
                No deadlines here yet — this map was compiled before Mnemify learned to
                read them. Run a fresh compile and phrases like{" "}
                <em className="text-muted">“by end of April”</em> or{" "}
                <em className="text-muted">“in 1 week”</em> will land in the buckets above.
              </p>
              <Button size="sm" variant="secondary" onClick={() => navigate("/build/compile")}>
                Compile again
              </Button>
            </div>
          )}
          {SECTIONS.map((section) => {
            const items = parts![section.key];
            if (items.length === 0) return null;
            const isCollapsed = collapsed.has(section.key);
            return (
              <ActionItemSection
                key={section.key}
                section={section}
                items={items}
                today={data.today}
                collapsed={isCollapsed}
                onToggle={() => toggle(section.key)}
                onDismiss={dismiss}
              />
            );
          })}
        </div>
      )}
    </PageShell>
  );
}

function ActionItemSection({
  section,
  items,
  today,
  collapsed,
  onToggle,
  onDismiss,
}: {
  section: (typeof SECTIONS)[number];
  items: ActionItem[];
  today: string;
  collapsed: boolean;
  onToggle: () => void;
  onDismiss: (id: string) => void;
}) {
  const { title, blurb, tone, icon: Icon } = section;
  const toneText: Record<Tone, string> = {
    danger: "text-danger",
    warning: "text-warning",
    info: "text-ink",
    neutral: "text-muted",
  };
  const Chevron = collapsed ? ChevronRight : ChevronDown;
  return (
    <Card className="overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!collapsed}
        className="w-full flex items-center gap-3 px-6 py-4 text-left hover:bg-bone/80 transition-colors"
      >
        <Chevron size={16} strokeWidth={1.75} className="text-muted shrink-0" aria-hidden />
        <Icon size={17} strokeWidth={1.75} className={cn("shrink-0", toneText[tone])} aria-hidden />
        <span className="font-serif text-lg text-ink leading-tight">{title}</span>
        <span
          className={cn(
            "font-sans text-xs tabular-nums px-2 py-0.5 rounded-full border",
            tone === "danger"
              ? "bg-danger/10 border-danger/30 text-danger"
              : tone === "warning"
                ? "bg-warning/10 border-warning/30 text-warning"
                : "bg-bone border-hair text-muted",
          )}
        >
          {items.length}
        </span>
        <span className="ml-auto font-sans text-xs text-muted hidden md:inline">{blurb}</span>
      </button>
      {!collapsed && (
        <div className="px-6 pb-4 divide-y divide-line/50 border-t border-hair">
          {items.map((item) => (
            <ActionItemRow
              key={item.id}
              item={item}
              tone={tone}
              today={today}
              onDismiss={onDismiss}
            />
          ))}
        </div>
      )}
    </Card>
  );
}

/** SeverityTag thresholds from the map's right panel (≥67 high, ≥34 medium). */
function severityDot(severity: number): string {
  if (severity >= 67) return "bg-danger";
  if (severity >= 34) return "bg-warning";
  return "bg-muted/50";
}

function ActionItemRow({
  item,
  tone,
  today,
  onDismiss,
}: {
  item: ActionItem;
  tone: Tone;
  today: string;
  onDismiss: (id: string) => void;
}) {
  const navigate = useNavigate();
  const due = dueLabel(item, today);
  const title = cleanTitle(item.title);
  const place = item.tag_label ?? item.region_label;
  return (
    <div className="group flex items-start gap-3.5 py-3.5">
      <span
        aria-hidden
        className={cn("mt-[7px] w-2 h-2 rounded-full shrink-0", severityDot(item.severity))}
        title={`Severity ${item.severity}`}
      />
      <div className="min-w-0 flex-1">
        <p className="font-sans text-[15px] text-ink leading-snug">{title}</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-sans text-xs text-muted">
          {due && (
            <Pill
              tone={tone === "danger" || tone === "warning" ? tone : "neutral"}
              className="px-2 py-0.5 text-[11px]"
            >
              {due}
            </Pill>
          )}
          {item.owner && <span className="text-ink/80">{item.owner}</span>}
          {place &&
            (item.tag_id ? (
              <button
                type="button"
                onClick={() => navigate(`/?tag=${encodeURIComponent(item.tag_id!)}`)}
                className="hover:text-ink underline decoration-line underline-offset-2 transition-colors"
              >
                {place}
              </button>
            ) : (
              <span>{place}</span>
            ))}
        </div>
      </div>
      <button
        type="button"
        aria-label={`Dismiss "${title}"`}
        title="Dismiss"
        onClick={() => onDismiss(item.id)}
        className={cn(
          "shrink-0 mt-0.5 p-1.5 rounded-full text-muted",
          "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
          "hover:text-ink hover:bg-bone transition-all",
        )}
      >
        <X size={15} strokeWidth={1.75} aria-hidden />
      </button>
    </div>
  );
}
