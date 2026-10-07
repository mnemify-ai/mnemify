import { describe, expect, it } from 'vitest';
import {
  buildTimelineIndex,
  changedBy,
  DAY_MS,
  isBornBy,
  notesBy,
  notesChangedBy,
  sliderDomain,
} from './timeline';
import type { Note, RenderData } from '../types';

const T0 = Date.parse('2025-01-10T00:00:00Z');
const d = (days: number) => new Date(T0 + days * DAY_MS).toISOString();

// Region tree: 0 = root "A", 1 = leaf "A1" (child of 0), 2 = leaf "B" (root).
const data = {
  regions: [
    { id: 'A', parentIdx: -1 },
    { id: 'A1', parentIdx: 0 },
    { id: 'B', parentIdx: -1 },
  ],
  tagIndex: ['t-early', 't-late', 't-undated'],
  hexes: [],
} as unknown as RenderData;

function note(partial: Partial<Note>): Note {
  return {
    id: 'n',
    title: '',
    source: 'obsidian',
    sourceUrl: '',
    author: '',
    createdAt: '',
    updatedAt: '',
    regionId: 'A1',
    primaryTagId: 't-early',
    tagIds: [],
    excerpt: '',
    wordCount: 0,
    ...partial,
  };
}

const notes: Note[] = [
  note({ id: 'n1', createdAt: d(0), updatedAt: d(5), primaryTagId: 't-early', tagIds: ['t-early'] }),
  note({ id: 'n2', createdAt: d(20), updatedAt: d(60), primaryTagId: 't-late', tagIds: ['t-late', 't-early'], regionId: 'B' }),
  note({ id: 'n3', createdAt: 'not a date', updatedAt: '', primaryTagId: 't-undated', tagIds: ['t-undated'] }),
];

describe('buildTimelineIndex', () => {
  const idx = buildTimelineIndex(data, notes)!;

  it('spans the earliest creation to the latest update', () => {
    expect(idx.minMs).toBe(T0);
    expect(idx.maxMs).toBe(T0 + 60 * DAY_MS);
    expect(Array.from(idx.noteCreated)).toEqual([T0, T0 + 20 * DAY_MS]);
  });

  it('dates a tag from every note that carries it', () => {
    expect(idx.tagFirstSeen[0]).toBe(T0); // t-early: n1
    expect(idx.tagLastTouched[0]).toBe(T0 + 60 * DAY_MS); // t-early also on n2
    expect(idx.tagFirstSeen[1]).toBe(T0 + 20 * DAY_MS);
    expect(Number.isNaN(idx.tagFirstSeen[2])).toBe(true);
  });

  it('rolls leaf dates up to the parent region', () => {
    expect(idx.regionFirstSeen[1]).toBe(T0); // A1 holds n1
    expect(idx.regionFirstSeen[0]).toBe(T0); // A inherits from A1
    expect(idx.regionFirstSeen[2]).toBe(T0 + 20 * DAY_MS); // B holds n2
  });

  it('returns null when no note has a parseable date', () => {
    expect(buildTimelineIndex(data, [notes[2]])).toBeNull();
    expect(buildTimelineIndex(data, [])).toBeNull();
  });

  it('uses the slider domain in whole days', () => {
    const { minDay, maxDay } = sliderDomain(idx);
    expect(minDay).toBe(Math.floor(T0 / DAY_MS));
    expect(maxDay).toBe(Math.ceil((T0 + 60 * DAY_MS) / DAY_MS));
  });
});

describe('isBornBy / changedBy / notesBy', () => {
  const idx = buildTimelineIndex(data, notes)!;

  it('flattens a tag spire until its first note exists', () => {
    expect(isBornBy(idx, 1, 2, T0 + 10 * DAY_MS)).toBe(false);
    expect(isBornBy(idx, 1, 2, T0 + 20 * DAY_MS)).toBe(true);
  });

  it('dates plain terrain from its region, and keeps undated hexes visible', () => {
    expect(isBornBy(idx, -1, 2, T0)).toBe(false); // region B not yet
    expect(isBornBy(idx, -1, 0, T0)).toBe(true); // region A via A1
    expect(isBornBy(idx, 2, 1, T0 - DAY_MS)).toBe(false); // undated tag falls back to A1 (born at T0)
    expect(isBornBy(idx, 2, 1, T0)).toBe(true);
  });

  it('marks a tag changed only inside the window ending at the cutoff', () => {
    const cutoff = T0 + 60 * DAY_MS;
    expect(changedBy(idx, 0, 1, cutoff)).toBe(true); // touched at day 60
    expect(changedBy(idx, 0, 1, cutoff + 31 * DAY_MS)).toBe(false); // window has slid past day 60
    expect(changedBy(idx, 0, 1, T0 + 40 * DAY_MS)).toBe(false); // not yet touched, last update is in the future
    expect(changedBy(idx, 2, 1, cutoff)).toBe(false); // undated tag never "changes"
  });

  it('counts notes created by a date, and inside the trailing window', () => {
    expect(notesBy(idx, T0 - 1)).toBe(0);
    expect(notesBy(idx, T0)).toBe(1);
    expect(notesBy(idx, T0 + 60 * DAY_MS)).toBe(2);
    expect(notesChangedBy(idx, T0 + 25 * DAY_MS, 10 * DAY_MS)).toBe(1);
    expect(notesChangedBy(idx, T0 + 60 * DAY_MS, 10 * DAY_MS)).toBe(0);
  });
});
