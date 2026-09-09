// Floating popover anchored to the selected tag's summit hex. Lists the
// OTHER top-level regions that tag semantically resembles, each with a
// weight bar. Replaces the old 3D cross-region arcs with an on-demand,
// click-driven surface (see plan: "the fix in principle").
//
// Mounted OUTSIDE the y-scale group in Scene.tsx, so the anchor's raw
// height is multiplied by yScale here — the convention every overlay that
// reads HexField's raw `tagSummitPos` map follows.

import { Html } from '@react-three/drei';
import type { RenderData } from '../types';
import { useKnowledgeMapStore } from '../store';
import { useTagRegionHighlight } from '../util/useTagRegionHighlight';
import { resolveTagLabel } from '../util/topLevelRegions';

const LIFT = 4; // apparent-space units above the spire summit

export function TagRelationPopover({
  data,
  yScale,
}: {
  data: RenderData;
  yScale: number;
}) {
  const selectedTagId = useKnowledgeMapStore((s) => s.selectedTagId);
  const tagSummitPos = useKnowledgeMapStore((s) => s.tagSummitPos);
  const setFocusRegion = useKnowledgeMapStore((s) => s.setFocusRegion);
  const highlight = useTagRegionHighlight(data);

  if (!selectedTagId || !highlight.hasRelated) return null;
  const pos = tagSummitPos.get(selectedTagId);
  if (!pos) return null;

  // Sorted strongest-first (backend already sorts; Map preserves that order).
  const rows = [...highlight.related.entries()];

  return (
    <Html
      position={[pos.x, pos.y * yScale + LIFT, pos.z]}
      center
      zIndexRange={[20, 0]}
      style={{ pointerEvents: 'auto', userSelect: 'none' }}
    >
      <div style={cardStyle}>
        <div style={titleStyle}>
          <span style={{ opacity: 0.6, fontStyle: 'italic' }}>also resembles</span>
          <br />
          {resolveTagLabel(data, selectedTagId)}
        </div>
        <div style={listStyle}>
          {rows.map(([regionIdx, weight]) => {
            const region = data.regions[regionIdx];
            if (!region) return null;
            return (
              <button
                key={region.id}
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setFocusRegion(regionIdx);
                }}
                title={`Focus ${region.name}`}
                style={rowStyle}
              >
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 2,
                    background: region.color,
                    flexShrink: 0,
                  }}
                />
                <span style={nameStyle}>{region.name}</span>
                <span style={barTrackStyle}>
                  <span
                    style={{
                      ...barFillStyle,
                      width: `${Math.round(Math.max(0, Math.min(1, weight)) * 100)}%`,
                      background: region.color,
                    }}
                  />
                </span>
                <span style={weightStyle}>{weight.toFixed(2)}</span>
              </button>
            );
          })}
        </div>
      </div>
    </Html>
  );
}

const cardStyle: React.CSSProperties = {
  minWidth: 180,
  maxWidth: 240,
  padding: '8px 10px',
  borderRadius: 8,
  background: 'rgb(var(--c-bg) / 0.94)',
  border: '1px solid rgb(var(--c-line) / 0.35)',
  boxShadow: '0 4px 14px rgb(0 0 0 / 0.32), inset 0 1px 0 rgb(255 255 255 / 0.14)',
  backdropFilter: 'blur(6px)',
  WebkitBackdropFilter: 'blur(6px)',
  fontFamily: 'ui-serif, "Newsreader", Georgia, serif',
  color: 'rgb(var(--c-ink))',
};

const titleStyle: React.CSSProperties = {
  fontSize: 12,
  lineHeight: 1.3,
  fontWeight: 600,
  marginBottom: 6,
  paddingBottom: 6,
  borderBottom: '1px solid rgb(var(--c-line) / 0.18)',
};

const listStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 2,
};

const rowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  width: '100%',
  padding: '3px 4px',
  border: 'none',
  borderRadius: 5,
  background: 'transparent',
  cursor: 'pointer',
  textAlign: 'left',
  fontFamily: 'inherit',
  color: 'rgb(var(--c-ink) / 0.88)',
};

const nameStyle: React.CSSProperties = {
  flex: 1,
  fontSize: 12,
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
};

const barTrackStyle: React.CSSProperties = {
  width: 40,
  height: 4,
  borderRadius: 2,
  background: 'rgb(var(--c-line) / 0.25)',
  flexShrink: 0,
  overflow: 'hidden',
};

const barFillStyle: React.CSSProperties = {
  display: 'block',
  height: '100%',
  borderRadius: 2,
};

const weightStyle: React.CSSProperties = {
  width: 26,
  textAlign: 'right',
  fontSize: 10,
  fontVariantNumeric: 'tabular-nums',
  color: 'rgb(var(--c-muted))',
  flexShrink: 0,
};
