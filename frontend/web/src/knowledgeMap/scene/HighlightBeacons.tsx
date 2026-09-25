// Beacons over the spires an Ask answer cited: an emissive orb above each
// summit plus a thin light column down to it. The hex recolour alone reads
// as "slightly brighter" from the default camera distance; these are what
// make a cited source unmistakable at any zoom. Mounted OUTSIDE the y-scale
// group, so summit y is multiplied by yScale here.
//
// Bloom (Scene.tsx) catches the emissive material, so the orbs glow without
// any per-frame animation — the frameloop stays on demand.

import { useMemo } from 'react';
import { Color } from 'three';
import { useKnowledgeMapStore } from '../store';

/** Hot accent for cited sources — deliberately NOT a region hue, so a lit
 *  spire never reads as "just a saturated region". */
export const HIGHLIGHT_ACCENT = '#FF2E88';

const ORB_RADIUS = 0.55;
const ORB_LIFT = 2.6;      // apparent-space units above the summit
const BEAM_RADIUS = 0.09;

export function HighlightBeacons({ yScale }: { yScale: number }) {
  const askHighlight = useKnowledgeMapStore((s) => s.askHighlight);
  const tagSummitPos = useKnowledgeMapStore((s) => s.tagSummitPos);

  const beacons = useMemo(() => {
    if (!askHighlight) return [];
    const out: { key: string; x: number; y: number; z: number }[] = [];
    for (const tagId of askHighlight.tagIds) {
      const p = tagSummitPos.get(tagId);
      if (!p) continue;
      out.push({ key: tagId, x: p.x, y: p.y * yScale, z: p.z });
    }
    return out;
  }, [askHighlight, tagSummitPos, yScale]);

  const accent = useMemo(() => new Color(HIGHLIGHT_ACCENT), []);
  if (beacons.length === 0) return null;

  return (
    <group>
      {beacons.map((b) => (
        <group key={b.key} position={[b.x, b.y, b.z]}>
          {/* Light column from the summit up to the orb. */}
          <mesh position={[0, ORB_LIFT / 2, 0]}>
            <cylinderGeometry args={[BEAM_RADIUS, BEAM_RADIUS, ORB_LIFT, 8]} />
            <meshBasicMaterial color={accent} transparent opacity={0.55} toneMapped={false} />
          </mesh>
          {/* The orb: emissive well past 1.0 so Bloom blooms it. */}
          <mesh position={[0, ORB_LIFT, 0]}>
            <sphereGeometry args={[ORB_RADIUS, 20, 16]} />
            <meshStandardMaterial
              color={accent}
              emissive={accent}
              emissiveIntensity={2.4}
              roughness={0.4}
              toneMapped={false}
            />
          </mesh>
          {/* Soft halo ring at the base so the summit itself reads as lit. */}
          <mesh position={[0, 0.06, 0]} rotation={[-Math.PI / 2, 0, 0]}>
            <ringGeometry args={[0.7, 1.15, 24]} />
            <meshBasicMaterial color={accent} transparent opacity={0.6} toneMapped={false} />
          </mesh>
        </group>
      ))}
    </group>
  );
}
