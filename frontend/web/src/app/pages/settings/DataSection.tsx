import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { toastReset, toastHarvestReset } from "../../lib/toast";
import { Trash2 } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { Segmented } from "../../components/ui/Segmented";
import { AlertDialog } from "../../components/ui/AlertDialog";
import { apiFetch } from "../../api/client";
import { useResetHarvest } from "../../api/harvest";
import {
  type RetentionPolicy,
  usePurgeNow,
  useRetention,
  useUpdateRetention,
} from "../../api/retention";
import { SettingsSection } from "./SettingsSection";
import { cn } from "../../lib/cn";

/** Returns the parsed integer if the text is a whole number in range, else null. */
function parseGrace(text: string): number | null {
  if (text.trim() === "") return null;
  const n = Number(text);
  if (!Number.isFinite(n) || !Number.isInteger(n)) return null;
  if (n < 0 || n > 365) return null;
  return n;
}

export function DataSection() {
  const qc = useQueryClient();
  const resetHarvest = useResetHarvest();
  const resetAll = useMutation({
    mutationFn: () => apiFetch<{ ok: boolean }>("/api/reset", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries(); // everything
      toastReset();
    },
    onError: (err) => toast.error("Couldn't reset", { description: String(err) }),
  });
  const [openHarvestReset, setOpenHarvestReset] = useState(false);
  const [openFullReset, setOpenFullReset] = useState(false);

  return (
    <div className="max-w-3xl">
      <RetentionSection />

      <SettingsSection
        eyebrow="Harvested data"
        title="Reset harvested data"
        help={
          <>
            Deletes every harvested document, the harvest log, and the compiled map
            (terrain, render-data, notes). Source connections and credentials stay —
            re-harvest and re-compile to rebuild. <strong>Can't be undone.</strong>
          </>
        }
      >
        <Button
          variant="secondary"
          onClick={() => setOpenHarvestReset(true)}
          disabled={resetHarvest.isPending}
        >
          <Trash2 size={14} strokeWidth={1.5} />
          Reset harvested data
        </Button>
      </SettingsSection>

      <SettingsSection
        eyebrow="Danger zone"
        title="Reset everything"
        help={
          <>
            Wipes all harvested data + the compiled map, <strong>plus</strong> disconnecting
            every source and removing its credentials from <code className="font-mono text-[11px]">.env</code>.
            You'll have to re-add your tokens. <strong>Can't be undone.</strong>
          </>
        }
      >
        <Button variant="secondary" onClick={() => setOpenFullReset(true)} disabled={resetAll.isPending}>
          <Trash2 size={14} strokeWidth={1.5} />
          Reset everything
        </Button>
      </SettingsSection>

      <AlertDialog
        open={openHarvestReset}
        onOpenChange={setOpenHarvestReset}
        title="Reset harvested data?"
        description="Deletes every harvested document + the compiled map. Connections and credentials are kept. This can't be undone."
        confirmLabel="Reset data"
        cancelLabel="Keep it"
        tone="destructive"
        confirming={resetHarvest.isPending}
        onConfirm={() =>
          resetHarvest.mutate(undefined, {
            onSuccess: () => {
              setOpenHarvestReset(false);
              toastHarvestReset();
            },
            onError: (err) => toast.error("Couldn't reset", { description: String(err) }),
          })
        }
      />
      <AlertDialog
        open={openFullReset}
        onOpenChange={setOpenFullReset}
        title="Reset everything?"
        description="Wipes all harvested data + the compiled map, AND disconnects every source and removes its credentials. You'll need to re-add your tokens. This can't be undone."
        confirmLabel="Reset everything"
        cancelLabel="Cancel"
        tone="destructive"
        confirming={resetAll.isPending}
        onConfirm={() => resetAll.mutate(undefined, { onSuccess: () => setOpenFullReset(false) })}
      />
    </div>
  );
}

const POLICY_OPTIONS: ReadonlyArray<{ value: RetentionPolicy; label: string }> = [
  { value: "keep", label: "Keep" },
  { value: "purge", label: "Auto-purge" },
];

const GRACE_MIN = 0;
const GRACE_MAX = 365;

function RetentionSection() {
  const { data, isLoading } = useRetention();
  const update = useUpdateRetention();
  const purgeNow = usePurgeNow();

  const [policy, setPolicy] = useState<RetentionPolicy>("keep");
  // The input is text-controlled so we can show invalid intermediate states
  // ("" or "abc") instead of silently coercing them to a saved value.
  const [graceText, setGraceText] = useState<string>("7");
  const [confirmPolicy, setConfirmPolicy] = useState(false);
  const [confirmPurgeNow, setConfirmPurgeNow] = useState(false);

  useEffect(() => {
    if (data) {
      setPolicy(data.on_source_delete);
      setGraceText(String(data.purge_grace_days));
    }
  }, [data?.on_source_delete, data?.purge_grace_days]);

  const deletedCount = data?.deleted_count ?? 0;
  const graceParsed = parseGrace(graceText);
  const graceValid = graceParsed !== null;

  function save(next: { on_source_delete: RetentionPolicy; purge_grace_days: number }) {
    update.mutate(next, {
      onSuccess: () => toast.success("Retention policy saved."),
      onError: (err) => toast.error("Couldn't save", { description: String(err) }),
    });
  }

  // Track the last-saved grace value separately so blur-saves don't double-fire
  // when the input value already matches the server.
  const lastSavedGraceRef = useRef<number | null>(null);
  useEffect(() => {
    if (data) lastSavedGraceRef.current = data.purge_grace_days;
  }, [data?.purge_grace_days]);

  function handlePolicyChange(next: RetentionPolicy) {
    setPolicy(next);
    if (data?.on_source_delete === next) return;
    // keep → purge is destructive (older deletions get flushed on the next
    // harvest); show the confirmation. Other transitions save immediately.
    if (data?.on_source_delete === "keep" && next === "purge") {
      setConfirmPolicy(true);
      return;
    }
    if (graceValid) {
      save({ on_source_delete: next, purge_grace_days: graceParsed });
    }
  }

  function commitGrace() {
    if (!graceValid || data == null) return;
    if (graceParsed === lastSavedGraceRef.current) return;
    lastSavedGraceRef.current = graceParsed;
    save({ on_source_delete: policy, purge_grace_days: graceParsed });
  }

  return (
    <SettingsSection
      eyebrow="Deletion policy"
      title="When a source deletes a document"
      help={
        <>
          Mnemify always notices when a document disappears at the source and marks it{" "}
          <code className="font-mono text-[11px]">deleted_at_source</code>. This setting
          decides whether the raw file is then removed automatically after a grace period,
          or kept until you purge manually.
        </>
      }
    >
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center gap-3">
          <Segmented<RetentionPolicy>
            value={policy}
            onValueChange={handlePolicyChange}
            options={POLICY_OPTIONS}
            ariaLabel="Deletion policy"
          />
          {policy === "purge" && (
            <label className="flex items-center gap-2 font-sans text-sm text-muted">
              <span>Purge after</span>
              <input
                type="number"
                min={GRACE_MIN}
                max={GRACE_MAX}
                step={1}
                value={graceText}
                aria-invalid={!graceValid}
                onChange={(e) => setGraceText(e.target.value)}
                onBlur={commitGrace}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    (e.target as HTMLInputElement).blur();
                  }
                }}
                className={cn(
                  "w-16 h-8 px-2 rounded-md border bg-bone/50 font-sans text-sm text-ink focus:outline-none transition-colors",
                  graceValid
                    ? "border-hair focus:border-ink/40"
                    : "border-rose/60 focus:border-rose",
                )}
              />
              <span>days</span>
              {!graceValid && (
                <span className="font-sans text-[11px] text-rose">
                  Enter a whole number from {GRACE_MIN} to {GRACE_MAX}.
                </span>
              )}
            </label>
          )}
        </div>

        <p className="font-sans text-xs text-muted max-w-prose">
          {policy === "keep"
            ? "Deleted documents stay in your library marked as removed at source. Use “Purge now” below to clean them out manually."
            : graceParsed === 0
              ? "Documents are purged immediately when they vanish from the source. Risky if a source API hiccups — pick a grace period for safety."
              : graceValid
                ? `Documents are purged ${graceParsed} day${graceParsed === 1 ? "" : "s"} after they're flagged deleted at source. Within the grace window you can still recover by re-harvesting if the source restores the file.`
                : "Pick a valid grace period to enable auto-purge."}
        </p>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="font-sans text-xs text-muted">
            {isLoading
              ? "Loading…"
              : update.isPending
                ? "Saving…"
                : deletedCount === 0
                  ? "No documents currently marked deleted at source."
                  : `${deletedCount} document${deletedCount === 1 ? "" : "s"} currently marked deleted at source.`}
          </span>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setConfirmPurgeNow(true)}
            disabled={deletedCount === 0 || purgeNow.isPending}
          >
            <Trash2 size={14} strokeWidth={1.5} />
            {purgeNow.isPending ? "Purging…" : "Purge now"}
          </Button>
        </div>
      </div>

      <AlertDialog
        open={confirmPolicy}
        onOpenChange={(open) => {
          setConfirmPolicy(open);
          // Cancelling the dialog reverts the toggle so the UI doesn't claim
          // to have switched when nothing actually saved.
          if (!open && data?.on_source_delete) setPolicy(data.on_source_delete);
        }}
        title="Switch to auto-purge?"
        description={`Documents will be removed ${graceParsed === 0 ? "immediately" : `${graceParsed ?? "?"} day${graceParsed === 1 ? "" : "s"}`} after they're flagged deleted at source. Previously deleted documents older than the grace period will be purged on the next harvest run. This can't be undone.`}
        confirmLabel="Turn on auto-purge"
        cancelLabel="Cancel"
        tone="destructive"
        confirming={update.isPending}
        onConfirm={() => {
          if (graceValid) save({ on_source_delete: "purge", purge_grace_days: graceParsed });
          setConfirmPolicy(false);
        }}
      />
      <AlertDialog
        open={confirmPurgeNow}
        onOpenChange={setConfirmPurgeNow}
        title="Purge deleted documents now?"
        description={`Permanently removes ${deletedCount} document${deletedCount === 1 ? "" : "s"} currently marked deleted at source, ignoring the grace period. This can't be undone.`}
        confirmLabel={`Purge ${deletedCount}`}
        cancelLabel="Cancel"
        tone="destructive"
        confirming={purgeNow.isPending}
        onConfirm={() =>
          purgeNow.mutate(undefined, {
            onSuccess: (r) => {
              setConfirmPurgeNow(false);
              toast.success(
                r.purged === 0
                  ? "Nothing to purge."
                  : `Purged ${r.purged} document${r.purged === 1 ? "" : "s"}.`,
              );
            },
            onError: (err) => toast.error("Couldn't purge", { description: String(err) }),
          })
        }
      />
    </SettingsSection>
  );
}
