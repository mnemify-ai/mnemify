import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Clock, CircleAlert, FolderPlus, FolderX, Plug, RefreshCw, TriangleAlert, Unplug } from "lucide-react";
import { sourceMeta } from "./SourceBadge";
import { LiveStatusBadge } from "./LiveStatusBadge";
import { Button } from "./ui/Button";
import { Pill } from "./ui/Pill";
import { cn } from "../lib/cn";
import { useHarvestCurrent, useStartHarvest } from "../api/harvest";
import { toast } from "sonner";
import { useRemoveLocalFilesRoot, type Connection } from "../api/connections";

export type CardState = "connected" | "not_connected" | "not_supported";

interface ConnectionCardProps {
  source: string;
  state: CardState;
  /** Live connection from /api/connections (null if not in YAML yet). */
  connection: Connection | null;
  /** When true: scroll-into-view + flash border (URL hash deep-link). */
  highlighted: boolean;
  /** Opens the source's wizard. */
  onConnect: () => void;
  /** Opens the AlertDialog confirming disconnect. */
  onDisconnect: () => void;
  /** Opens the manage-scope dialog (only for connected, supported sources). */
  onManageScope?: () => void;
}

export function ConnectionCard({
  source,
  state,
  connection,
  highlighted,
  onConnect,
  onDisconnect,
  onManageScope,
}: ConnectionCardProps) {
  const meta = sourceMeta(source);
  const ref = useRef<HTMLElement>(null);
  const [flashing, setFlashing] = useState(highlighted);
  const startHarvest = useStartHarvest();
  // Poll the harvest state so the pending-scope notice can stand down while
  // a harvest is in flight. Without this the count appears stuck or churns
  // on every page nav while the run is still pulling docs.
  const harvestCurrent = useHarvestCurrent({ poll: true });
  const navigate = useNavigate();
  const removeRoot = useRemoveLocalFilesRoot();
  const isLocalFiles = source === "localfiles";

  useEffect(() => {
    if (!highlighted) return;
    setFlashing(true);
    ref.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    const t = window.setTimeout(() => setFlashing(false), 1800);
    return () => window.clearTimeout(t);
  }, [highlighted]);

  const isConnected = state === "connected";
  const isComingSoon = state === "not_supported";
  const hasHarvested =
    isConnected && connection && connection.doc_count > 0 && !!connection.last_harvest_at;

  function handleReharvest() {
    startHarvest.mutate(
      { sources: [source] },
      {
        onSuccess: () => {
          toast.success(`Harvesting ${meta.label}…`);
          navigate("/build/harvest");
        },
        onError: (err) => {
          toast.error(`Couldn't start harvest`, { description: String(err) });
        },
      },
    );
  }

  return (
    <article
      ref={ref}
      id={source}
      className={cn(
        "relative bg-bone/60 border rounded-2xl p-6 transition-shadow",
        flashing ? "border-magenta shadow-[0_0_0_4px_rgb(var(--c-magenta)/0.18)]" : "border-hair",
        isComingSoon && "opacity-75",
      )}
    >
      <header className="flex items-start justify-between gap-4 mb-5">
        <div className="flex items-center gap-3">
          <span
            className={cn(
              "h-10 w-10 rounded-xl flex items-center justify-center shrink-0",
              meta.dotClass,
            )}
          >
            <span className="font-serif italic text-lg text-cream">
              {meta.label.charAt(0)}
            </span>
          </span>
          <div>
            <h3 className="font-serif text-2xl text-ink leading-none">{meta.label}</h3>
            <p className="font-sans text-[11px] text-muted mt-1.5 uppercase tracking-eyebrow">
              {isConnected
                ? hasHarvested
                  ? "Connected"
                  : "Connected · awaiting first harvest"
                : isComingSoon
                  ? "Available in v2.x"
                  : "Not connected"}
            </p>
          </div>
        </div>
        <StatusPill state={state} />
      </header>

      {/* Body — real data only. */}
      {isConnected && hasHarvested && connection ? (
        <div className="mb-4 flex items-center gap-3 flex-wrap">
          <LiveStatusBadge connection={connection} />
          <button
            type="button"
            onClick={() => navigate(`/documents#${source}`)}
            className="inline-flex items-center gap-1 font-sans text-[11px] text-muted hover:text-ink transition-colors"
          >
            View {connection.doc_count.toLocaleString()} document
            {connection.doc_count === 1 ? "" : "s"}
            <ArrowRight size={11} strokeWidth={1.75} aria-hidden />
          </button>
        </div>
      ) : isConnected ? (
        <p className="mb-4 font-sans text-sm text-muted">
          Connected, but nothing harvested yet — run a harvest to populate Mnemify.
        </p>
      ) : !isComingSoon ? (
        <p className="mb-4 font-sans text-sm text-muted max-w-prose">
          {isLocalFiles
            ? "Link one or more folders of .md, .txt or .pdf files on this computer. They're read in place — nothing is uploaded."
            : `Not connected. Add your ${meta.label} credentials to start harvesting documents into your Knowledge Map.`}
        </p>
      ) : null}

      {/* Local files: the linked folders. One source, many folders — each
          row can be unlinked on its own; "Add another folder" in the footer
          reopens the wizard, which appends rather than replaces. */}
      {isLocalFiles && isConnected && connection?.roots && connection.roots.length > 0 && (
        <ul className="mb-4 divide-y divide-hair/60 rounded-xl border border-hair bg-cream/40">
          {connection.roots.map((r) => (
            <li key={r.path} className="flex items-center gap-3 px-3 py-2">
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5">
                  <span className="font-serif text-sm text-ink truncate">{r.name}</span>
                  {!r.exists && (
                    <span
                      className="inline-flex items-center gap-1 font-sans text-[10px] text-warning"
                      title="This folder can't be found right now"
                    >
                      <TriangleAlert size={11} strokeWidth={2} aria-hidden />
                      missing
                    </span>
                  )}
                </span>
                <span className="block font-mono text-[10px] text-muted truncate" title={r.path}>
                  {r.path}
                  {r.watch_folders.length > 0 &&
                    ` · ${r.watch_folders.length} item${r.watch_folders.length === 1 ? "" : "s"} in scope`}
                </span>
              </span>
              <button
                type="button"
                onClick={() =>
                  removeRoot.mutate(r.path, {
                    onSuccess: () =>
                      toast.success(`Unlinked ${r.name}.`, {
                        description: "Its documents drop out on the next harvest. Nothing on disk changes.",
                      }),
                    onError: (err) => toast.error("Couldn't unlink folder", { description: String(err) }),
                  })
                }
                disabled={removeRoot.isPending}
                aria-label={`Unlink ${r.name}`}
                title="Unlink this folder"
                className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-rose/10 hover:text-rose disabled:opacity-50"
              >
                <FolderX size={14} strokeWidth={1.5} aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* Scope-drift notice: rendered when the user has added scope items
          since the last completed harvest. Suppressed while any harvest is
          in flight — otherwise the count drifts on every refetch and the
          notice looks broken to the user. Once the run completes, the
          backend snapshots the new scope, so this notice disappears
          automatically on the next refetch of /api/connections. */}
      {isConnected &&
        connection &&
        connection.pending_scope_count > 0 &&
        harvestCurrent.data?.status !== "running" && (
          <div className="mb-4 flex items-start gap-2 rounded-xl border border-magenta/25 bg-magenta/[0.04] px-3 py-2.5">
            <CircleAlert
              size={14}
              strokeWidth={1.75}
              aria-hidden
              className="mt-0.5 shrink-0 text-magenta"
            />
            <p className="font-sans text-xs text-ink leading-snug">
              <span className="font-medium">
                {connection.pending_scope_count} new scope item
                {connection.pending_scope_count === 1 ? "" : "s"} since last harvest.
              </span>{" "}
              <span className="text-muted">
                Click {hasHarvested ? "Re-harvest" : "Run harvest"} to pull
                {connection.pending_scope_count === 1 ? " it" : " them"} in.
              </span>
            </p>
          </div>
        )}

      {/* Coming-soon cards have no action footer — the section heading already
          says "Available in a later v2.x" so per-card text would be redundant. */}
      {!isComingSoon && (
      <footer className="flex items-center justify-between gap-2 pt-4 border-t border-hair">
        {isConnected ? (
          <>
            <div className="flex items-center gap-1.5 flex-wrap">
              {hasHarvested ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleReharvest}
                  disabled={startHarvest.isPending}
                >
                  <RefreshCw size={14} strokeWidth={1.5} />
                  Re-harvest
                </Button>
              ) : (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleReharvest}
                  disabled={startHarvest.isPending}
                >
                  <RefreshCw size={14} strokeWidth={1.5} />
                  Run harvest
                </Button>
              )}
              {isLocalFiles && (
                <Button variant="secondary" size="sm" onClick={onConnect}>
                  <FolderPlus size={14} strokeWidth={1.5} />
                  Add another folder
                </Button>
              )}
              {onManageScope && (
                <button
                  type="button"
                  onClick={onManageScope}
                  className="font-sans text-[11px] text-muted hover:text-ink px-2.5 py-1.5 rounded-full transition-[color,transform] duration-fast ease-out active:scale-[0.99]"
                >
                  Manage scope
                </button>
              )}
            </div>
            <button
              type="button"
              onClick={onDisconnect}
              className="inline-flex items-center gap-1.5 font-sans text-[11px] text-muted hover:text-rose px-2 py-1.5 rounded-full transition-[color,transform] duration-fast ease-out active:scale-[0.99]"
            >
              <Unplug size={12} strokeWidth={1.5} />
              {meta.verb.remove}
            </button>
          </>
        ) : (
          <Button variant="primary" size="sm" onClick={onConnect}>
            <Plug size={14} strokeWidth={1.5} />
            {meta.verb.add} {meta.label}
          </Button>
        )}
      </footer>
      )}
    </article>
  );
}

// Semantic mapping: connected → success (sage IS --c-success), not_connected
// → neutral, not_supported → info (lavender). `CardState` doesn't include an
// `error` variant — nothing to map for danger here.
function StatusPill({ state }: { state: CardState }) {
  if (state === "connected") {
    // Use Pill `dot` so the live indicator carries the semantic color, then
    // override just the dot to animate so the "alive" pulse is on the dot
    // rather than the whole pill.
    return (
      <Pill
        tone="success"
        dot
        className="text-xs [&>span:first-child]:animate-pulse motion-reduce:[&>span:first-child]:animate-none"
      >
        Connected
      </Pill>
    );
  }
  if (state === "not_supported") {
    // Distinct from "Not connected": info tint + italic + clock icon —
    // communicates "not yet available", not "broken" or "clickable".
    return (
      <Pill tone="info" className="text-xs italic cursor-default">
        <Clock size={11} strokeWidth={1.75} aria-hidden />
        Coming soon
      </Pill>
    );
  }
  return (
    <Pill tone="neutral" className="text-xs">
      Not connected
    </Pill>
  );
}
