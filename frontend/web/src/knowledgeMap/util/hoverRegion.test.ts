// Hover feedback must land on the region the user can SEE as a unit at the
// current level — the top-level region at the map root, the immediate child
// of the open region inside one — never the leaf and never unrelated terrain.

import { describe, expect, it } from 'vitest';
import { resolveHoverChild } from './hoverRegion';
import { buildAncestorChains } from './regionTerrain';
import type { RegionEntry } from '../types';

const region = (id: string, parentIdx: number, level: number): RegionEntry =>
  ({ id, name: id, level, parentIdx }) as unknown as RegionEntry;

/**
 *   0 top_a
 *     1 child_a
 *       2 grandchild_a
 *     3 child_b
 *   4 top_b
 */
const chains = buildAncestorChains([
  region('top_a', -1, 0),
  region('child_a', 0, 1),
  region('grandchild_a', 1, 2),
  region('child_b', 0, 1),
  region('top_b', -1, 0),
]);

describe('resolveHoverChild', () => {
  it('resolves to the top-level ancestor at the map root', () => {
    expect(resolveHoverChild(chains, 2, null)).toBe(0);
    expect(resolveHoverChild(chains, 0, null)).toBe(0);
    expect(resolveHoverChild(chains, 4, null)).toBe(4);
  });

  it('resolves to the immediate child of the focused region', () => {
    expect(resolveHoverChild(chains, 2, 0)).toBe(1);   // grandchild → child_a
    expect(resolveHoverChild(chains, 3, 0)).toBe(3);   // child_b is itself the child
    expect(resolveHoverChild(chains, 2, 1)).toBe(2);   // one level deeper
  });

  it('ignores terrain outside the focused region', () => {
    expect(resolveHoverChild(chains, 4, 0)).toBeNull();
    expect(resolveHoverChild(chains, 3, 1)).toBeNull();
  });

  it("ignores the focused region's own terrain — there is no child to light", () => {
    expect(resolveHoverChild(chains, 0, 0)).toBeNull();
    expect(resolveHoverChild(chains, 2, 2)).toBeNull();
  });

  it('is null-safe', () => {
    expect(resolveHoverChild(chains, null, 0)).toBeNull();
    expect(resolveHoverChild(chains, 99, null)).toBeNull();
  });
});
