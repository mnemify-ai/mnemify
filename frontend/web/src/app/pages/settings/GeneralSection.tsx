import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Moon, RefreshCw, Sparkles, Sun } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { useMapData } from "../../data/MapDataProvider";
import { useTerrainReport } from "../../api/terrain";
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
    </div>
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
