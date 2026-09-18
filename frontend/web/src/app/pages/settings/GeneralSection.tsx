import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Moon, Power, RefreshCw, Sparkles, Sun } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { AlertDialog } from "../../components/ui/AlertDialog";
import { useMapData } from "../../data/MapDataProvider";
import { useTerrainReport } from "../../api/terrain";
import { useHealth, useServerSettings, useShutdown, useUpdateServerSettings } from "../../api/system";
import { relativeTime } from "../../lib/relativeTime";
import { formatDuration } from "../../lib/formatEta";
import { useThemeMode } from "../../lib/useThemeMode";
import { cn } from "../../lib/cn";
import { SettingsSection } from "./SettingsSection";

export function GeneralSection() {
  const navigate = useNavigate();
  const report = useTerrainReport();
  const mapData = useMapData();
  const [theme, setTheme] = useThemeMode();

  const r = report.data;
  const aiLabel =
    r?.ai_mode === "local"
      ? "local heuristics"
      : r?.ai_mode === "openai"
        ? "OpenAI"
        : r?.ai_mode === "claude"
          ? "Claude (subscription)"
          : "—";

  function reload() {
    mapData.refetch();
    report.refetch();
    toast.success("Reloading…", { description: "Re-fetching the compiled map + report." });
  }

  return (
    <div className="max-w-3xl">
      <SettingsSection
        eyebrow="Display"
        title="Theme"
        help="Switches between the canonical cream palette and an after-dark variant with the same brand hues. Motion respects your OS prefers-reduced-motion setting. The TopBar moon/sun button toggles the same setting."
      >
        <div className="grid grid-cols-2 gap-2 max-w-md">
          <ThemeButton
            active={theme === "light"}
            onClick={() => setTheme("light")}
            icon={<Sun size={16} strokeWidth={1.5} aria-hidden />}
            label="Cream"
            desc="The canonical look"
          />
          <ThemeButton
            active={theme === "dark"}
            onClick={() => setTheme("dark")}
            icon={<Moon size={16} strokeWidth={1.5} aria-hidden />}
            label="Ink"
            desc="Same brand, after dark"
          />
        </div>
      </SettingsSection>

      <SettingsSection
        eyebrow="Your Knowledge Map"
        title="Compiled snapshot"
        help="Stats about the last compile run — when it finished, how long it took, how many regions, tags, and notes your map currently knows about."
        actions={
          <Button variant="secondary" size="sm" onClick={reload}>
            <RefreshCw size={14} strokeWidth={1.5} />
            Reload
          </Button>
        }
      >
        {report.isLoading ? (
          <p className="font-sans text-sm text-muted animate-pulse">Loading…</p>
        ) : !r?.exists ? (
          <div>
            <p className="font-sans text-sm text-muted mb-4 max-w-prose">
              Nothing compiled yet — harvest some documents, then compile to build your Knowledge Map.
            </p>
            <Button variant="primary" size="sm" onClick={() => navigate("/build/compile")}>
              <Sparkles size={14} strokeWidth={1.5} />
              Go to Compile
            </Button>
          </div>
        ) : (
          <>
            <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-4">
              <Stat label="Compiled" value={r.generated_at ? relativeTime(r.generated_at) : "—"} />
              <Stat label="Mode" value={aiLabel} />
              <Stat label="Took" value={r.seconds != null ? formatDuration(r.seconds) : "—"} />
              <Stat label="Regions" value={(r.stats?.regions ?? 0).toLocaleString()} />
              <Stat label="Tags" value={(r.stats?.tagsTotal ?? 0).toLocaleString()} />
              <Stat label="Notes" value={(r.stats?.notes ?? 0).toLocaleString()} />
            </dl>
            <div className="mt-5 flex flex-wrap items-center gap-3">
              <Button variant="secondary" size="sm" onClick={() => navigate("/build/compile")}>
                <RefreshCw size={14} strokeWidth={1.5} />
                Recompile
              </Button>
              <Button variant="ghost" size="sm" onClick={() => navigate("/")}>
                View your map →
              </Button>
              {mapData.empty && (
                <span className="font-sans text-[11px] text-rose">map didn't render — recompile to fix</span>
              )}
            </div>
          </>
        )}
      </SettingsSection>

      <AppSection />
    </div>
  );
}

// ─── Application: version, idle shutdown, quit ─────────────────────────────

const IDLE_MIN = 0;
const IDLE_MAX = 24 * 60;

/** The parsed whole number of minutes, or null if the text isn't usable yet. */
function parseIdleMinutes(text: string): number | null {
  if (text.trim() === "") return null;
  const n = Number(text);
  if (!Number.isFinite(n) || !Number.isInteger(n)) return null;
  if (n < IDLE_MIN || n > IDLE_MAX) return null;
  return n;
}

function AppSection() {
  const health = useHealth();
  const settings = useServerSettings();
  const update = useUpdateServerSettings();
  const shutdown = useShutdown();

  const [minutesText, setMinutesText] = useState("30");
  const [confirmQuit, setConfirmQuit] = useState(false);
  const [stopped, setStopped] = useState(false);
  const lastSavedRef = useRef<number | null>(null);

  useEffect(() => {
    if (settings.data) {
      setMinutesText(String(settings.data.idle_timeout_minutes));
      lastSavedRef.current = settings.data.idle_timeout_minutes;
    }
  }, [settings.data?.idle_timeout_minutes]);

  const parsed = parseIdleMinutes(minutesText);
  const valid = parsed !== null;

  function commitIdleTimeout() {
    if (parsed === null || parsed === lastSavedRef.current) return;
    lastSavedRef.current = parsed;
    update.mutate(
      { idle_timeout_minutes: parsed },
      {
        onSuccess: () => toast.success("Idle shutdown saved."),
        onError: (err) => toast.error("Couldn't save", { description: String(err) }),
      },
    );
  }

  function quit() {
    shutdown.mutate(undefined, {
      onSuccess: () => {
        setConfirmQuit(false);
        setStopped(true);
      },
      onError: (err) => {
        setConfirmQuit(false);
        toast.error("Couldn't stop Mnemify", { description: String(err) });
      },
    });
  }

  if (stopped) {
    return (
      <SettingsSection eyebrow="Application" title="Mnemify has stopped">
        <p className="font-sans text-sm text-muted max-w-prose">
          You can close this tab. Start it again from the Mnemify icon, or with{" "}
          <code className="font-mono text-xs">mnemify up</code>.
        </p>
      </SettingsSection>
    );
  }

  const version = health.data?.version;
  const commitSha = health.data?.commit;

  return (
    <SettingsSection
      eyebrow="Application"
      title="This copy of Mnemify"
      help="Mnemify runs as a local server on your own machine. It can quit itself when you stop using it, and you can stop it here at any time — your harvested data and compiled map are on disk and survive a restart."
      actions={
        <Button variant="secondary" size="sm" onClick={() => setConfirmQuit(true)}>
          <Power size={14} strokeWidth={1.5} />
          Quit Mnemify
        </Button>
      }
    >
      <div className="flex flex-col gap-5">
        <p className="font-sans text-sm text-muted tabular-nums">
          {version ? (
            <>
              Mnemify v{version}
              {commitSha ? ` (${commitSha})` : ""}
            </>
          ) : (
            "Mnemify — version unavailable"
          )}
        </p>

        <div>
          <label className="flex flex-wrap items-center gap-2 font-sans text-sm text-muted">
            <span className="text-ink">Idle shutdown</span>
            <span>after</span>
            <input
              type="number"
              min={IDLE_MIN}
              max={IDLE_MAX}
              step={1}
              value={minutesText}
              aria-invalid={!valid}
              aria-label="Idle shutdown in minutes"
              disabled={settings.isLoading}
              onChange={(e) => setMinutesText(e.target.value)}
              onBlur={commitIdleTimeout}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  (e.target as HTMLInputElement).blur();
                }
              }}
              className={cn(
                "w-16 h-8 px-2 rounded-md border bg-bone/50 font-sans text-sm text-ink focus:outline-none transition-colors",
                valid ? "border-hair focus:border-ink/40" : "border-rose/60 focus:border-rose",
              )}
            />
            <span>minutes of inactivity</span>
            {!valid && (
              <span className="font-sans text-[11px] text-rose">
                Enter a whole number from {IDLE_MIN} to {IDLE_MAX}.
              </span>
            )}
          </label>
          <p className="font-sans text-xs text-muted max-w-prose mt-2">
            {parsed === 0
              ? "Never quits on its own — it runs until you quit it or restart your machine."
              : "Suspended while any harvest schedule is enabled, and never while a harvest, compile or chat is running."}
          </p>
        </div>
      </div>

      <AlertDialog
        open={confirmQuit}
        onOpenChange={setConfirmQuit}
        title="Quit Mnemify?"
        description="The server stops and this tab goes offline. Nothing is deleted — start it again from the Mnemify icon whenever you want."
        confirmLabel="Quit"
        cancelLabel="Cancel"
        tone="destructive"
        confirming={shutdown.isPending}
        onConfirm={quit}
      />
    </SettingsSection>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="eyebrow mb-1">{label}</dt>
      <dd className="font-serif text-lg text-ink tabular-nums">{value}</dd>
    </div>
  );
}

function ThemeButton({
  active,
  onClick,
  icon,
  label,
  desc,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  desc: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex flex-col items-start gap-1.5 px-4 py-3.5 rounded-xl border text-left transition-colors",
        active ? "bg-ink text-cream border-ink" : "bg-bone/40 text-ink border-hair hover:bg-bone",
      )}
    >
      <span className="flex items-center gap-2">
        {icon}
        <span className="font-serif text-base">{label}</span>
      </span>
      <span className={cn("font-sans text-xs", active ? "text-cream/70" : "text-muted")}>{desc}</span>
    </button>
  );
}
