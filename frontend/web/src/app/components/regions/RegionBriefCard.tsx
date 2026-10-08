import { useLayoutEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, RefreshCw, Sparkles } from "lucide-react";
import { SectionCard } from "./SectionCard";
import { Pill } from "../ui/Pill";
import { Skeleton } from "../ui/Skeleton";
import { AssistantMarkdown } from "../../../ask/AssistantMarkdown";
import { useAskSettingsStore } from "../../../ask/askSettingsStore";
import { activeKey, wireProvider } from "../../../ask/types";
import { streamOverviewRefresh } from "../../api/regionOverview";
import type { RegionBrief } from "../../api/regions";
import { qk } from "../../api/keys";
import { cn } from "../../lib/cn";
import { relativeTime } from "../../lib/relativeTime";
import { toastError } from "../../lib/toast";

/**
 * The region brief. Shows the compiler's `compiled_note` until the user asks
 * for a refresh, which re-synthesizes it with the BYOK chat model from what
 * the compiler can't see: saved memory, confirmed/dismissed items and recent
 * source changes. The refreshed text streams in and is kept server-side.
 *
 * Collapsed to a few lines by default so the workspace leads with evidence,
 * not prose; "Read full brief" expands it in place.
 */
export function RegionBriefCard({
  regionId,
  brief,
  loading,
  fallbackSummary,
}: {
  regionId: string;
  brief: RegionBrief | null | undefined;
  loading: boolean;
  fallbackSummary: string | null;
}) {
  const qc = useQueryClient();
  const settings = useAskSettingsStore((s) => s.settings);
  const [streaming, setStreaming] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);

  const refresh = async () => {
    if (streaming !== null) return;
    setStreaming("");
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamOverviewRefresh(
        regionId,
        { provider: wireProvider(settings), model: settings.model },
        activeKey(settings),
        (t) => setStreaming((prev) => (prev ?? "") + t),
        controller.signal,
      );
      await qc.invalidateQueries({ queryKey: qk.region(regionId) });
    } catch (e) {
      if (!(e instanceof Error && e.name === "AbortError")) {
        toastError(e instanceof Error ? e.message : "Could not refresh the overview.");
      }
    } finally {
      setStreaming(null);
      abortRef.current = null;
    }
  };

  const text = streaming ?? brief?.text ?? fallbackSummary ?? "";
  const open = expanded || streaming !== null;
  // Only offer the toggle when the collapsed box actually clips something.
  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el || open) return;
    setOverflows(el.scrollHeight > el.clientHeight + 2);
  }, [text, open]);

  return (
    <SectionCard
      eyebrow="Region brief"
      bodyClassName="pt-2 pb-4"
      action={
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={streaming !== null}
          className="inline-flex items-center gap-1.5 font-sans text-xs text-muted transition-colors hover:text-magenta disabled:opacity-60"
          title="Re-synthesize this brief with your saved memory and recent changes"
        >
          {streaming !== null ? <RefreshCw size={12} className="animate-spin" aria-hidden /> : <Sparkles size={12} aria-hidden />}
          {streaming !== null ? "Refreshing…" : "Refresh"}
        </button>
      }
    >
      {loading && !text ? (
        <div className="space-y-2">
          <Skeleton width="92%" />
          <Skeleton width="86%" />
          <Skeleton width="60%" />
        </div>
      ) : text ? (
        <div
          ref={bodyRef}
          className={cn(
            "font-serif text-[15px] leading-relaxed text-ink [&_h2]:font-sans [&_h2]:text-xs [&_h2]:uppercase [&_h2]:tracking-eyebrow [&_h2]:text-muted [&_h2]:mt-4 [&_h2]:mb-1 [&_strong]:font-semibold [&_p]:mb-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-2 [&>*:last-child]:mb-0 [&_p:last-child]:mb-0",
            !open && "max-h-[4.75rem] overflow-hidden [mask-image:linear-gradient(to_bottom,black_55%,transparent)]",
          )}
        >
          {brief?.source === "refreshed" || streaming !== null ? (
            <AssistantMarkdown text={text} citations={[]} />
          ) : (
            text.split(/\n{2,}/).map((para, i) => <p key={i}>{para}</p>)
          )}
        </div>
      ) : (
        <p className="font-sans text-sm text-muted">No brief yet — compile the map, or refresh to write one.</p>
      )}
      {(overflows || expanded) && streaming === null ? (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="mt-2 inline-flex items-center gap-1 font-sans text-xs text-magenta hover:underline underline-offset-4"
        >
          {expanded ? "Show less" : "Read full brief"}
          <ChevronDown size={13} strokeWidth={1.75} className={cn("transition-transform", expanded && "rotate-180")} aria-hidden />
        </button>
      ) : null}
      {brief?.source === "refreshed" && streaming === null && open ? (
        <div className="mt-3 flex items-center gap-2 font-sans text-[11px] text-muted">
          <Pill tone="info" className="px-2 py-0.5 text-[10px]">Refreshed</Pill>
          {brief.created_at ? <span>{relativeTime(brief.created_at)}</span> : null}
          {brief.model ? <span>· {brief.model}</span> : null}
        </div>
      ) : null}
    </SectionCard>
  );
}
