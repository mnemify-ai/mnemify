import { describe, expect, it } from 'vitest';
import { highlightTopLevelIdx, resolveAskHighlight } from './askHighlight';
import type { Note, RenderData } from '../types';

// Two top-level regions (0, 1); region 2 is a child of 0. Tag t0 lives in
// region 2, tag t1 in region 1.
const data = {
  regions: [
    { id: 'r0', parentIdx: -1 },
    { id: 'r1', parentIdx: -1 },
    { id: 'r2', parentIdx: 0 },
  ],
  tagIndex: ['t0', 't1'],
  // [q, r, regionIdx, height, tagIdx]
  hexes: [0, 0, 2, 5, 0, 1, 0, 1, 5, 1, 2, 0, 1, 1, -1],
} as unknown as RenderData;

const note = (over: Partial<Note>): Note =>
  ({ id: 'n-1', regionId: 'r1', primaryTagId: 't1', tagIds: ['t1', 't0'], ...over }) as Note;

describe('resolveAskHighlight', () => {
  it('keeps only tags and regions present in this bake', () => {
    const out = resolveAskHighlight(data, null, {
      tagIds: ['t0', 'ghost'],
      regionIds: ['r1', 'nope'],
      noteIds: [],
      label: 'q',
      token: 1,
    });
    expect([...out.tagIds]).toEqual(['t0']);
    expect([...out.regionIdxs]).toEqual([1]);
    expect(out.label).toBe('q');
    expect(out.token).toBe(1);
  });

  it('resolves a note to its primary tag and region', () => {
    const notes = new Map([['n-1', note({})]]);
    const out = resolveAskHighlight(data, notes, {
      tagIds: [],
      regionIds: [],
      noteIds: ['n-1'],
      label: '',
      token: 2,
    });
    expect([...out.tagIds]).toEqual(['t1']);
    expect([...out.regionIdxs]).toEqual([1]);
  });

  it('falls back to every tag when the primary is not on the map', () => {
    const notes = new Map([['n-1', note({ primaryTagId: 'gone', tagIds: ['gone', 't0'] })]]);
    const out = resolveAskHighlight(data, notes, {
      tagIds: [],
      regionIds: [],
      noteIds: ['n-1'],
      label: '',
      token: 3,
    });
    expect([...out.tagIds]).toEqual(['t0']);
  });

  it('ignores notes while the notes file is not loaded', () => {
    const out = resolveAskHighlight(data, null, {
      tagIds: [],
      regionIds: [],
      noteIds: ['n-1'],
      label: '',
      token: 4,
    });
    expect(out.tagIds.size).toBe(0);
  });
});

describe('highlightTopLevelIdx', () => {
  const base = { label: '', token: 1 };
  it('returns the single top-level region, walking up from a child', () => {
    expect(
      highlightTopLevelIdx(data, { ...base, tagIds: new Set(['t0']), regionIdxs: new Set([2]) }),
    ).toBe(0);
  });
  it('returns null (frame home) when the highlight spans top-level regions', () => {
    expect(
      highlightTopLevelIdx(data, { ...base, tagIds: new Set(['t0', 't1']), regionIdxs: new Set() }),
    ).toBeNull();
  });
  it('returns undefined when nothing resolved', () => {
    expect(
      highlightTopLevelIdx(data, { ...base, tagIds: new Set(), regionIdxs: new Set() }),
    ).toBeUndefined();
  });
});
