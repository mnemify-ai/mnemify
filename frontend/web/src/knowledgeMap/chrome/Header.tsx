// Top-left title strip. Sits above the canvas via absolute positioning;
// pointer-events:none so it doesn't intercept orbit drags.

import type { RenderData } from '../types';

const serifCls = "font-[ui-serif,Georgia,'Times_New_Roman',serif]";

export function Header({ data }: { data: RenderData }) {
  const topLevelCount = data.regions.filter((r) => r.level === 0).length;
  return (
    <div className="absolute top-7 left-9 z-[5] pointer-events-none select-none">
      <div className={`text-[11px] tracking-[0.22em] text-muted uppercase ${serifCls}`}>
        Knowledge Density Map
      </div>
      <div className={`text-[56px] leading-none font-normal text-ink mt-1.5 tracking-[-0.01em] ${serifCls}`}>
        Mnemify
      </div>
      <div className={`text-[16px] text-ink/[0.78] mt-1.5 ${serifCls}`}>
        Your Knowledge Map · {data.tagIndex.length} tags · {topLevelCount} regions
      </div>
    </div>
  );
}
