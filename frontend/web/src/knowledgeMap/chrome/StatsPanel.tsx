// At-a-glance counts. Now an inline-flow strip — the parent BottomBar
// owns positioning so the strip can live in a real grid row rather than
// floating absolutely over the canvas.

import type { RenderData } from '../types';

export function StatsPanel({ data }: { data: RenderData }) {
  const tops = data.regions.filter((r) => r.level === 0).length;
  const subs = data.regions.filter((r) => r.level === 1).length;
  const subsubs = data.regions.filter((r) => r.level === 2).length;

  return (
    <div className="select-none font-[ui-serif,Georgia,'Times_New_Roman',serif] flex gap-[22px] flex-wrap">
      <Stat label="Tags"          value={data.tagIndex.length} />
      <Stat label="Top regions"   value={tops} />
      <Stat label="Sub-regions"   value={subs + subsubs} />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-[10px] tracking-[0.22em] text-muted uppercase">{label}</span>
      <span className="text-[14px] text-ink font-medium">{value}</span>
    </div>
  );
}
