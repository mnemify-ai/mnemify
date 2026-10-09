import { useEffect } from "react";
import { useHarvestCurrent } from "../api/harvest";
import { useStartCompile } from "../api/terrain";
import { useCompileAfterHarvest } from "../lib/compileAfterHarvestStore";
import { toastError, toastInfo, toastSuccess } from "../lib/toast";

/**
 * Runs the compile queued by "Harvest, then compile" once that harvest ends.
 * Renders nothing; mounted once in DashboardLayout so it outlives the dialog
 * that queued it.
 */
export function CompileAfterHarvest() {
  const payload = useCompileAfterHarvest((s) => s.payload);
  const queuedAt = useCompileAfterHarvest((s) => s.queuedAt);
  const clear = useCompileAfterHarvest((s) => s.clear);
  // Poll only while something is queued; OpsPill polls during a run anyway.
  const harvest = useHarvestCurrent({ poll: payload !== null, idlePollMs: 3_000 });
  const startCompile = useStartCompile();

  const status = harvest.data?.status;
  const finishedAt = harvest.data?.finished_at ?? null;

  useEffect(() => {
    if (!payload || queuedAt === null) return;
    if (status === "running" || finishedAt === null || finishedAt < queuedAt) return;
    clear();
    if (status !== "complete") {
      toastInfo("Harvest didn't finish, so the compile was skipped.");
      return;
    }
    startCompile.mutate(payload, {
      onSuccess: (res) => {
        if (res.ok) toastSuccess("Harvest done — compiling your map…");
        // "Compile automatically after harvest" (Settings) may have beaten us
        // to it; that compile is the one the user asked for.
        else if (res.dismissed || /already running/.test(res.reason ?? "")) return;
        else toastError("Couldn't start compile", { description: res.reason });
      },
      onError: (err) => toastError("Couldn't start compile", { description: String(err) }),
    });
    // startCompile is a fresh object each render; the payload guard above
    // keeps this from firing twice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload, queuedAt, status, finishedAt, clear]);

  return null;
}
