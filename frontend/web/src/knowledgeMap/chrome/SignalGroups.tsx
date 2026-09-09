// Highlights tab body: attention signals grouped by kind (risks, decisions,
// open questions, …), each with a per-kind accent colour and icon. Shared by
// the region and tag detail views.

import { useMemo } from 'react';
import {
  AlertTriangle, CircleCheckBig, HelpCircle, ListTodo, User, Clock, Check,
  type LucideIcon,
} from 'lucide-react';
import type { AttentionSignal, Note } from '../types';
import { emptyBaseCls } from './panelShared';

// Per-kind identity: a label, an accent colour, and an icon, so each kind of
// highlight reads at a glance instead of looking like every other row. Ordered
// by what a product owner triages first. Raw hexes are intentional — these are
// severity accents shared with the map overlay, not theme surfaces.
type KindMeta = { label: string; color: string; Icon: LucideIcon };
const KIND_META: Record<AttentionSignal['kind'], KindMeta> = {
  risk: { label: 'Risks', color: '#E11D48', Icon: AlertTriangle },
  decision: { label: 'Decisions', color: '#16A34A', Icon: CircleCheckBig },
  open_question: { label: 'Open questions', color: '#F59E0B', Icon: HelpCircle },
  todo: { label: 'To-dos', color: '#2563EB', Icon: ListTodo },
  owner: { label: 'Owners', color: '#7048E8', Icon: User },
  recent_change: { label: 'Recent changes', color: '#0891B2', Icon: Clock },
};
const KIND_ORDER: AttentionSignal['kind'][] = [
  'risk', 'decision', 'open_question', 'todo', 'owner', 'recent_change',
];
const RESOLVED_STATUSES = new Set([
  'resolved', 'closed', 'done', 'complete', 'completed', 'approved', 'decided', 'shipped',
]);

export function SignalGroups({
  signals,
  notesById,
}: {
  signals: AttentionSignal[];
  notesById: Map<string, Note>;
}) {
  const groups = useMemo(
    () => KIND_ORDER
      .map((kind) => ({ kind, rows: signals.filter((s) => s.kind === kind) }))
      .filter((g) => g.rows.length > 0),
    [signals],
  );
  if (groups.length === 0) return null;
  return (
    <div className="flex flex-col gap-4">
      {groups.map((group) => {
        const meta = KIND_META[group.kind];
        const { Icon } = meta;
        return (
          <div key={group.kind}>
            <div className="flex items-center gap-1.5 mb-[7px] text-[10px] tracking-[0.12em] uppercase font-semibold">
              <Icon size={13} color={meta.color} strokeWidth={2.25} aria-hidden />
              <span style={{ color: meta.color }}>{meta.label}</span>
              <span
                className="ml-px text-[9.5px] font-bold rounded-full px-1.5 leading-[15px] tabular-nums"
                style={{ color: meta.color, background: `${meta.color}1A` }}
              >
                {group.rows.length}
              </span>
            </div>
            <div className="flex flex-col gap-1.5">
              {group.rows.slice(0, 6).map((signal) => (
                <div
                  key={signal.id}
                  className="py-[7px] pr-2 pl-[9px] rounded-md border border-line/[0.22] border-l-[3px] bg-bone/[0.35]"
                  // Left accent tracks the kind colour — stays inline.
                  style={{ borderLeftColor: meta.color }}
                >
                  <div className="flex gap-2 items-start justify-between text-[12.5px] leading-[1.35] text-ink/90">
                    <span>{signal.title.replace(/^(Todo|Risk|Decision|Open Question|Owner|Recent Change):\s*/, '')}</span>
                    <SeverityTag signal={signal} />
                  </div>
                  {signal.owner && <div className={signalMetaCls}>Owner: {signal.owner}</div>}
                  {(signal.status || sourceLabel(signal, notesById)) && (
                    <div className={signalMetaCls}>
                      {signal.status}
                      {sourceLabel(signal, notesById)}
                    </div>
                  )}
                </div>
              ))}
              {group.rows.length > 6 && (
                <div className={`${emptyBaseCls} py-0.5`}>+{group.rows.length - 6} more</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

const signalMetaCls = 'mt-[3px] text-[11px] leading-[1.3] text-muted';

// Right-aligned status: a green check for resolved/decided items, otherwise a
// colour-tiered severity pill (high / med / low). Hidden when neither applies.
function SeverityTag({ signal }: { signal: AttentionSignal }) {
  if (signal.status && RESOLVED_STATUSES.has(signal.status.toLowerCase())) {
    return <Check size={14} color="#16A34A" strokeWidth={2.5} aria-label="resolved" className="shrink-0" />;
  }
  const s = signal.severity;
  if (!s || s <= 0) return null;
  const tier = s >= 67 ? { label: 'high', color: '#E11D48' }
    : s >= 34 ? { label: 'med', color: '#F59E0B' }
      : { label: 'low', color: '#6B7280' };
  return (
    <span
      className="shrink-0 text-[9px] font-bold tracking-[0.04em] uppercase rounded-full px-1.5 py-px"
      // Tier colour drives text/border/wash — stays inline.
      style={{ color: tier.color, border: `1px solid ${tier.color}55`, background: `${tier.color}14` }}
    >
      {tier.label}
    </span>
  );
}

function sourceLabel(signal: AttentionSignal, notesById: Map<string, Note>): string {
  const titles = signal.source_note_ids
    .map((id) => notesById.get(id)?.title)
    .filter(Boolean)
    .slice(0, 2);
  return titles.length ? ` · ${titles.join(', ')}` : '';
}
