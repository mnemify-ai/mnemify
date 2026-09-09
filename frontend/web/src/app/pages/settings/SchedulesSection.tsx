import { useId, useState } from "react";
import { toast } from "sonner";
import { toastScheduleOn } from "../../lib/toast";
import { Clock, Trash2 } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { SettingsSection } from "./SettingsSection";
import { useConnections } from "../../api/connections";
import {
  useDeleteSchedule,
  useSchedules,
  useUpsertSchedule,
  type Schedule,
} from "../../api/schedules";
import { cn } from "../../lib/cn";

// The backend scheduler runs cron in UTC, but nobody thinks in UTC — presets
// are named in the user's local time and converted to a UTC cron on the spot.
// (Stored crons are fixed UTC instants, so they won't shift with DST.)
function dailyUtcCron(localHour: number): string {
  const d = new Date();
  d.setHours(localHour, 0, 0, 0);
  return `${d.getUTCMinutes()} ${d.getUTCHours()} * * *`;
}

function weeklyUtcCron(localWeekday: number, localHour: number): string {
  const d = new Date();
  d.setDate(d.getDate() + ((localWeekday - d.getDay() + 7) % 7));
  d.setHours(localHour, 0, 0, 0);
  return `${d.getUTCMinutes()} ${d.getUTCHours()} * * ${d.getUTCDay()}`;
}

const PRESETS: { label: string; cron: string }[] = [
  { label: "Every morning at 6am", cron: dailyUtcCron(6) },
  { label: "Every 6 hours", cron: "0 */6 * * *" },
  { label: "Every hour", cron: "0 * * * *" },
  { label: "Every Monday at 9am", cron: weeklyUtcCron(1, 9) },
  { label: "Custom", cron: "" },
];

function presetFor(cron: string): string {
  const match = PRESETS.find((p) => p.cron === cron);
  return match ? match.label : "Custom";
}

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** "in 20m" / "in 5h" / "in 2d" for a future ISO timestamp. */
function untilText(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(ms) || ms <= 0) return "any moment now";
  const minutes = Math.round(ms / 60_000);
  if (minutes < 60) return `in ${Math.max(minutes, 1)}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `in ${hours}h`;
  return `in ${Math.round(hours / 24)}d`;
}

function localTimeOf(utcHour: number, utcMinute: number): string {
  const d = new Date();
  d.setUTCHours(utcHour, utcMinute, 0, 0);
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

/** Plain-language summary of a cron, in the user's local time. Returns null
 *  for shapes we can't confidently describe (shown as-is instead). */
function describeCron(cron: string): string | null {
  const m = cron.trim().match(/^(\d{1,2}) (\d{1,2}|\*|\*\/\d{1,2}) \* \* (\d|\*)$/);
  if (!m) return null;
  const [, minute, hourField, dow] = m;
  if (hourField.startsWith("*/")) {
    const every = Number(hourField.slice(2));
    return `Runs every ${every} hours`;
  }
  if (hourField === "*") return "Runs every hour";
  const time = localTimeOf(Number(hourField), Number(minute));
  if (dow === "*") return `Runs daily at ${time} your time`;
  // The stored weekday is UTC; derive the local weekday from a concrete date.
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + ((Number(dow) - d.getUTCDay() + 7) % 7));
  d.setUTCHours(Number(hourField), Number(minute), 0, 0);
  return `Runs every ${WEEKDAYS[d.getDay()]} at ${time} your time`;
}

export function SchedulesSection() {
  const connections = useConnections();
  const schedules = useSchedules();
  const sources = (connections.data ?? []).filter((c) => c.status === "connected");

  return (
    <div className="max-w-3xl">
      <SettingsSection
        eyebrow="Automation"
        title="Scheduled harvests"
        help="Pick when each source checks for new and changed pages. Times are shown in your local time. Runs happen while the server is up."
      >
        {connections.isLoading || schedules.isLoading ? (
          <p className="font-sans text-sm text-muted animate-pulse motion-reduce:animate-none">Loading…</p>
        ) : sources.length === 0 ? (
          <div className="py-8 text-center">
            <p className="font-serif text-lg text-ink mb-2">No connected sources</p>
            <p className="font-sans text-sm text-muted max-w-prose mx-auto">
              Connect a source first, then come back to schedule it.
            </p>
          </div>
        ) : (
          <div className="flex flex-col">
            {sources.map((c, i) => (
              <ScheduleRow
                key={c.source}
                source={c.source}
                schedule={schedules.data?.schedules[c.source] ?? null}
                index={i}
              />
            ))}
          </div>
        )}
      </SettingsSection>
    </div>
  );
}

function ScheduleRow({
  source,
  schedule,
  index,
}: {
  source: string;
  schedule: Schedule | null;
  index: number;
}) {
  const upsert = useUpsertSchedule();
  const remove = useDeleteSchedule();
  const whenSelectId = useId();
  const customCronId = useId();

  const [preset, setPreset] = useState<string>(() =>
    schedule?.cron ? presetFor(schedule.cron) : "Every morning at 6am",
  );
  const [customCron, setCustomCron] = useState<string>(() =>
    schedule?.cron && !PRESETS.some((p) => p.cron === schedule.cron) ? schedule.cron : "",
  );
  const enabled = schedule?.enabled ?? false;

  const cronForPreset = PRESETS.find((p) => p.label === preset)?.cron ?? "";
  const effectiveCron = preset === "Custom" ? customCron.trim() : cronForPreset;
  const canSave = effectiveCron.length > 0;

  function save(nextEnabled: boolean) {
    if (!canSave) {
      toast.error("Cron expression required.");
      return;
    }
    upsert.mutate(
      { source, cron: effectiveCron, enabled: nextEnabled },
      {
        onSuccess: () => {
          if (nextEnabled) {
            toastScheduleOn(source, effectiveCron);
          } else {
            toast.success("Schedule saved.");
          }
        },
        onError: (err) => toast.error("Couldn't save schedule", { description: String(err) }),
      },
    );
  }

  function clear() {
    remove.mutate(source, {
      onSuccess: () => toast.success("Schedule removed."),
      onError: (err) => toast.error("Couldn't remove schedule", { description: String(err) }),
    });
  }

  // 30ms per-row stagger, capped at index 7 (same rule as audit log).
  const staggerDelay = `${Math.min(index, 7) * 30}ms`;

  return (
    <div
      className="py-4 first:pt-0 last:pb-0 border-b border-hair last:border-b-0 animate-fade-in motion-reduce:animate-none"
      style={{ animationDelay: staggerDelay }}
    >
      <header className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <Clock size={14} strokeWidth={1.5} className="text-muted" aria-hidden />
          <span className="font-serif text-base text-ink capitalize">{source}</span>
        </div>
        <div className="flex items-center gap-2">
          {schedule && (
            <button
              type="button"
              onClick={() => save(!enabled)}
              disabled={upsert.isPending || !canSave}
              className={cn(
                "font-sans text-xs px-3 py-1 rounded-full border transition-colors",
                enabled
                  ? "bg-sage/15 text-sage border-sage/40"
                  : "bg-bone/60 text-muted border-hair hover:text-ink",
              )}
            >
              {enabled ? "On" : "Off"}
            </button>
          )}
          {schedule && (
            <Button
              variant="ghost"
              size="sm"
              onClick={clear}
              disabled={remove.isPending}
              aria-label={`Remove ${source} schedule`}
              className="relative before:content-[''] before:absolute before:inset-[-6px]"
            >
              <Trash2 size={12} strokeWidth={1.5} aria-hidden />
            </Button>
          )}
        </div>
      </header>

      <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-3 items-end">
        <div>
          <label htmlFor={whenSelectId} className="block font-sans text-[11px] uppercase tracking-eyebrow text-muted mb-1.5">
            When
          </label>
          <select
            id={whenSelectId}
            value={preset}
            onChange={(e) => setPreset(e.target.value)}
            className="w-full font-sans text-sm px-3 py-2 rounded-lg border border-hair bg-bone/40 text-ink"
          >
            {PRESETS.map((p) => (
              <option key={p.label} value={p.label}>
                {p.label}
              </option>
            ))}
          </select>
          {preset === "Custom" && (
            <>
              <input
                id={customCronId}
                aria-label="Custom cron expression"
                type="text"
                value={customCron}
                onChange={(e) => setCustomCron(e.target.value)}
                placeholder="cron: minute hour day month weekday  (e.g. 0 6 * * *)"
                className="mt-2 w-full font-mono text-xs px-3 py-2 rounded-lg border border-hair bg-bone/40 text-ink placeholder:text-muted"
              />
              <p className="font-sans text-xs text-muted mt-1.5">
                Cron expression in UTC — for schedules the presets can't express.
              </p>
            </>
          )}
          {effectiveCron && (
            <p className="font-sans text-xs text-muted mt-1.5">
              {describeCron(effectiveCron) ?? `Cron: ${effectiveCron} (UTC)`}
            </p>
          )}
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={() => save(true)}
          disabled={upsert.isPending || !canSave}
        >
          {schedule ? "Update" : "Save"}
        </Button>
      </div>

      {schedule?.next_run && enabled && (
        <p className="font-sans text-xs text-muted mt-3 tabular-nums">
          Next run {untilText(schedule.next_run)}{" "}
          <span className="text-muted/70">
            (
            {new Date(schedule.next_run).toLocaleString(undefined, {
              weekday: "short",
              hour: "numeric",
              minute: "2-digit",
            })}
            )
          </span>
        </p>
      )}
    </div>
  );
}
