// Hex coordinate ↔ world position helpers, matching the Python bake.
// Pointy-top axial coords:
//   x = apothem * (2q + r)
//   z = apothem * sqrt(3) * r

const SQRT3 = Math.sqrt(3);

export function hexToWorld(q: number, r: number, apothem: number): [number, number] {
  return [apothem * (2 * q + r), apothem * SQRT3 * r];
}
