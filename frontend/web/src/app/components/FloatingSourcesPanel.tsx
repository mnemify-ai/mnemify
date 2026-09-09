import { useNavigate } from "react-router-dom";
import { useConnections } from "../api/connections";
import { sourceMeta } from "./SourceBadge";
import { relativeTime } from "../lib/relativeTime";
import { cn } from "../lib/cn";
import { Tooltip } from "./ui/Tooltip";

/** Floating panel on the map page — the live, connected sources and their
 *  real harvested-doc counts (from /api/connections). */
export function FloatingSourcesPanel() {
  const navigate = useNavigate();
  const connections = useConnections();
  const connected = (connections.data ?? []).filter((c) => c.status === "connected");
  const totalDocs = connected.reduce((sum, c) => sum + (c.doc_count ?? 0), 0);

  return (
    <section
      aria-label="Connected sources"
      className="glass-panel rounded-2xl w-[280px] overflow-hidden shadow-sm"
    >
      <header className="px-4 pt-3 pb-2 flex items-baseline justify-between">
        <span className="eyebrow">Sources</span>
        <span className="font-sans text-xs text-muted tabular-nums">
          {totalDocs.toLocaleString()} doc{totalDocs === 1 ? "" : "s"}
        </span>
      </header>
      {connected.length === 0 ? (
        <div className="px-4 pb-3">
          <p className="font-sans text-xs text-muted mb-2">No sources connected.</p>
          <button
            type="button"
            onClick={() => navigate("/build/sources")}
            className="font-sans text-[11px] text-magenta hover:underline"
          >
            Connect a source →
          </button>
        </div>
      ) : (
        <>
        <ul className="px-1 pb-1">
          {connected.map((c) => {
            const meta = sourceMeta(c.source);
            const harvested = (c.doc_count ?? 0) > 0 && !!c.last_harvest_at;
            const lastHarvestLabel = c.last_harvest_at
              ? `Last harvested ${relativeTime(c.last_harvest_at)}`
              : "Not yet harvested";
            const docCountText = `${(c.doc_count ?? 0).toLocaleString()} doc${
              c.doc_count === 1 ? "" : "s"
            }`;
            // Screen-reader contract: source name + connected status + doc count
            // + last-harvest. The visible dot is decorative (aria-hidden).
            const ariaLabel = `${meta.label}: connected, ${docCountText}, ${
              c.last_harvest_at
                ? `last harvested ${relativeTime(c.last_harvest_at)}`
                : "not yet harvested"
            }`;
            return (
              <li key={c.source}>
                <Tooltip content={lastHarvestLabel} side="right">
                  <button
                    type="button"
                    onClick={() => navigate(`/documents#${c.source}`)}
                    aria-label={ariaLabel}
                    className={cn(
                      "w-full text-left px-3 py-2 rounded-xl flex items-center gap-2.5",
                      "transition-colors hover:bg-bone/60 focus:bg-bone/60",
                    )}
                  >
                    <span className={cn("h-2 w-2 rounded-full shrink-0", meta.dotClass)} aria-hidden />
                    <span className="min-w-0 flex-1" aria-hidden>
                      <span className="block font-serif text-sm text-ink">{meta.label}</span>
                      <span className="block font-sans text-[11px] text-muted">
                        {harvested
                          ? `${docCountText} · ${relativeTime(c.last_harvest_at!)}`
                          : "awaiting first harvest"}
                      </span>
                    </span>
                    <span
                      className="font-sans text-[11px] text-muted tabular-nums shrink-0"
                      aria-hidden
                    >
                      {(c.doc_count ?? 0).toLocaleString()}
                    </span>
                  </button>
                </Tooltip>
              </li>
            );
          })}
        </ul>
        {totalDocs === 0 && (
          <div className="px-4 pt-3 pb-4 border-t border-hair/50">
            <p className="font-sans text-xs text-muted leading-relaxed mb-3">
              Nothing harvested yet. Run a harvest to fill this map.
            </p>
            <button
              type="button"
              onClick={() => navigate("/build/harvest")}
              className="font-sans text-[11px] text-magenta hover:underline"
            >
              Run a harvest →
            </button>
          </div>
        )}
        </>
      )}
    </section>
  );
}
