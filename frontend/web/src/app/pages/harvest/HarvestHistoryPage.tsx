import { PageShell } from "../../layouts/PageShell";
import { HarvestHistoryList } from "../../components/HarvestHistoryList";
import { BuildSectionTabs } from "../../components/BuildSectionTabs";
import { useHarvestHistory } from "../../api/harvest";

/** Dedicated full-list view of past harvest runs. The Status sub-tab still
 *  shows a recent-runs strip when idle; this page is for when the user
 *  wants the full picture. */
export function HarvestHistoryPage() {
  const history = useHarvestHistory();
  const runs = history.data?.runs ?? [];

  return (
    <PageShell
      title={runs.length === 0 ? "No harvests yet" : "Harvest history"}
      description={
        runs.length === 0
          ? "Once you connect a source and run a harvest, you'll see every run logged here."
          : `${runs.length} recorded run${runs.length === 1 ? "" : "s"}.`
      }
      tabs={<BuildSectionTabs />}
    >
      <HarvestHistoryList runs={runs} />
    </PageShell>
  );
}
