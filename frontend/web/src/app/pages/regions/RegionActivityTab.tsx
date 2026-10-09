import { useMemo } from "react";
import { MessageSquare } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { ErrorState } from "../../components/ui/ErrorState";
import { Skeleton } from "../../components/ui/Skeleton";
import { ChangeRow, groupChanges } from "../../components/RecentChangesPanel";
import { useRegionChanges, useRegionThreads } from "../../api/regions";
import { relativeTime } from "../../lib/relativeTime";
import { resumeThread } from "../../../ask/threadSync";
import { useRegionWorkspaceContext } from "./useRegionWorkspace";

export function RegionActivityTab() {
  const { regionId, askRegion } = useRegionWorkspaceContext();
  const threads = useRegionThreads(regionId);
  const changes = useRegionChanges(regionId, "last_compile");
  const days = useMemo(() => groupChanges(changes.data?.changes ?? []), [changes.data]);

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <section className="rounded-2xl border border-hair bg-bone/40 px-5 py-4">
        <div className="flex items-center justify-between gap-3">
          <p className="eyebrow">Conversations · {threads.data?.threads.length ?? 0}</p>
          <Button size="sm" variant="secondary" onClick={askRegion}>New conversation</Button>
        </div>
        {threads.isLoading ? (
          <div className="mt-3 space-y-2"><Skeleton width="70%" /><Skeleton width="50%" /></div>
        ) : threads.isError ? (
          <ErrorState title="Couldn't load conversations" onRetry={() => void threads.refetch()} className="py-6" />
        ) : (threads.data?.threads.length ?? 0) === 0 ? (
          <p className="mt-3 font-sans text-sm text-muted">No conversations in this region yet. Ask it something and the thread will be filed here.</p>
        ) : (
          <ul className="mt-2 divide-y divide-hair/70">
            {threads.data!.threads.map((t) => (
              <li key={t.id}>
                <button type="button" onClick={() => void resumeThread(t.id)} className="group flex w-full items-center gap-3 py-3 text-left">
                  <span className="inline-grid h-9 w-9 shrink-0 place-items-center rounded-full bg-lavender/40 text-ink">
                    <MessageSquare size={15} strokeWidth={1.75} aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-sans text-sm font-semibold text-ink group-hover:text-magenta">{t.title}</span>
                    <span className="block font-sans text-xs text-muted">
                      {t.message_count} message{t.message_count === 1 ? "" : "s"} · {relativeTime(t.updated_at)}
                      {t.region_id && t.region_id !== regionId && t.region_name ? ` · in ${t.region_name}` : ""}
                    </span>
                  </span>
                  <span className="font-sans text-xs text-magenta opacity-0 transition-opacity group-hover:opacity-100">Resume →</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="rounded-2xl border border-hair bg-bone/40 px-5 py-4">
        <p className="eyebrow">Source changes since the last compile · {changes.data?.changes.length ?? 0}</p>
        {changes.isLoading ? (
          <div className="mt-3 space-y-2"><Skeleton width="70%" /><Skeleton width="50%" /></div>
        ) : changes.isError ? (
          <ErrorState title="Couldn't load changes" onRetry={() => void changes.refetch()} className="py-6" />
        ) : days.length === 0 ? (
          <p className="mt-3 font-sans text-sm text-muted">
            Nothing in this region changed since the last compile.
            {changes.data && changes.data.unmapped_count > 0 ? ` ${changes.data.unmapped_count} new document${changes.data.unmapped_count === 1 ? "" : "s"} await the next compile.` : ""}
          </p>
        ) : (
          <div className="mt-2 space-y-4">
            {days.map((d) => (
              <div key={d.label}>
                <p className="font-sans text-[11px] uppercase tracking-eyebrow text-muted">{d.label}</p>
                {d.authors.map((a) => (
                  <div key={a.name} className="mt-1">
                    <p className="font-sans text-xs text-muted">{a.name}</p>
                    {a.entries.map((e) => <ChangeRow key={`${e.source}:${e.source_id}`} entry={e} />)}
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
