import { formatDistanceToNowStrict } from "date-fns";
import { History } from "lucide-react";
import { useChanges } from "../api/changes";
import { useStartHarvest } from "../api/harvest";
import type { CompileStartPayload } from "../api/terrain";
import { isStaleForCompile } from "../lib/briefing";
import { useCompileAfterHarvest } from "../lib/compileAfterHarvestStore";
import { toastError, toastSuccess } from "../lib/toast";
import { cn } from "../lib/cn";
import { Button } from "./ui/Button";

/**
 * Shown next to a compile action when the last harvest is a week or more
 * old: compiling now would build the map from stale data. Offers to harvest
 * first and compile when it's done (CompileAfterHarvest runs the second
 * half); the surface's own Compile button stays the "compile anyway" path.
 */
export function StaleHarvestNotice({
  payload,
  onQueued,
  className,
}: {
  /** The compile to run after the harvest — the same overrides the surface's
   *  own Compile button would send. */
  payload: CompileStartPayload;
  /** Called once the harvest has started (e.g. to close the dialog). */
  onQueued?: () => void;
  className?: string;
}) {
  const { data: changes } = useChanges();
  const startHarvest = useStartHarvest();
  const queue = useCompileAfterHarvest((s) => s.queue);
  const clear = useCompileAfterHarvest((s) => s.clear);

  if (!changes || changes.harvest_running || !isStaleForCompile(changes.last_harvest_time)) {
    return null;
  }
  const age = formatDistanceToNowStrict(new Date(changes.last_harvest_time!), { addSuffix: true });

  const harvestThenCompile = () => {
    // Queue first: a harvest with nothing new can finish before the next poll.
    queue(payload);
    startHarvest.mutate(
      { sources: null },
      {
        onSuccess: (res) => {
          if (!res.ok) {
            clear();
            toastError("Couldn't start harvest", { description: res.reason });
            return;
          }
          toastSuccess("Harvesting your sources…", {
            description: "Your map will compile as soon as it's done.",
          });
          onQueued?.();
        },
        onError: (err) => {
          clear();
          toastError("Couldn't start harvest", { description: String(err) });
        },
      },
    );
  };

  return (
    <div
      role="status"
      className={cn(
        "flex items-start gap-3 rounded-xl border border-warning/40 bg-warning/10 px-4 py-3",
        className,
      )}
    >
      <History size={16} strokeWidth={1.75} className="mt-0.5 shrink-0 text-ink" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-sans text-sm font-semibold text-ink">
          Your sources were last harvested {age}
        </p>
        <p className="mt-0.5 font-sans text-xs text-muted">
          Anything added or edited since then won't be on the map. Harvest first to include it.
        </p>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          className="mt-2.5"
          onClick={harvestThenCompile}
          loading={startHarvest.isPending}
        >
          Harvest, then compile
        </Button>
      </div>
    </div>
  );
}
