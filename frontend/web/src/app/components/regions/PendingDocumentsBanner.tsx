import { useQueryClient } from "@tanstack/react-query";
import { Inbox, Sparkles } from "lucide-react";
import { Button } from "../ui/Button";
import { useChanges } from "../../api/changes";
import { useRegionChanges } from "../../api/regions";
import { qk } from "../../api/keys";
import { useStartCompile } from "../../api/terrain";
import { toastError } from "../../lib/toast";

/**
 * Documents harvested since the last compile that this workspace can't
 * reflect yet: ones in this region that changed (the map still holds their
 * old version) plus new ones that have no note anywhere on the map. Always
 * measured against the last compile — not the last visit — because that is
 * what a compile would pick up. Renders nothing when there is nothing to do.
 */
export function PendingDocumentsBanner({ regionId }: { regionId: string }) {
  const region = useRegionChanges(regionId, "last_compile");
  const global = useChanges("last_compile");
  const startCompile = useStartCompile();
  const qc = useQueryClient();

  const changedHere = region.data?.changes.length ?? 0;
  const unmapped = region.data?.unmapped_count ?? 0;
  const total = changedHere + unmapped;
  if (!region.data || total === 0) return null;

  const compiling = Boolean(global.data?.compile_running);
  const harvesting = Boolean(global.data?.harvest_running);
  const plus = region.data.truncated ? "+" : "";
  const parts = [
    changedHere > 0 ? `${changedHere}${plus} changed in this region` : null,
    unmapped > 0 ? `${unmapped} new, not on the map yet` : null,
  ].filter(Boolean);

  return (
    <section
      aria-label="Documents waiting to be processed"
      className="flex flex-wrap items-center gap-4 rounded-2xl border border-warning/40 bg-warning/10 px-5 py-4"
    >
      <span className="inline-grid h-10 w-10 shrink-0 place-items-center rounded-full bg-warning/20 text-ink">
        <Inbox size={18} strokeWidth={1.75} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-sans text-sm font-semibold text-ink">
          {total}{plus} document{total === 1 ? "" : "s"} waiting to be processed
        </p>
        <p className="mt-0.5 font-sans text-xs text-muted">
          {parts.join(" · ")}. Decisions, questions and action items below don't include them until the map is recompiled.
        </p>
      </div>
      <Button
        onClick={() =>
          startCompile.mutate({}, {
            onSuccess: (r) => {
              if (!r.ok && !r.dismissed) toastError(r.reason ?? "Could not start processing.");
              // Pick up compile_running now rather than on the next poll.
              void qc.invalidateQueries({ queryKey: qk.changes("last_compile") });
            },
            onError: (e) => toastError(e instanceof Error ? e.message : "Could not start processing."),
          })
        }
        disabled={compiling || harvesting || startCompile.isPending}
        loading={startCompile.isPending}
        className="gap-2"
      >
        <Sparkles size={14} strokeWidth={1.75} aria-hidden />
        {compiling ? "Processing…" : harvesting ? "Waiting for harvest…" : "Process now"}
      </Button>
    </section>
  );
}
