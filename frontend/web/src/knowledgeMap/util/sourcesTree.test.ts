import { describe, expect, it } from 'vitest';
import type { Note } from '../types';
import { buildSourcesTree, filterSourcesTree, notePath, pathKeysTo, type SourceTreeGroup } from './sourcesTree';

let seq = 0;
function note(partial: Partial<Note> & Pick<Note, 'title' | 'source'>): Note {
  seq += 1;
  return {
    id: `n-${seq}`,
    sourceUrl: '',
    author: 'Maya Chen',
    createdAt: '2026-09-01T00:00:00Z',
    updatedAt: '2026-09-01T00:00:00Z',
    regionId: 'r',
    primaryTagId: 't',
    tagIds: [],
    excerpt: '',
    wordCount: 100,
    ...partial,
  };
}

describe('notePath', () => {
  it('prefers docPath, then sourceDetail, then nothing', () => {
    expect(notePath(note({ title: 'a', source: 'notion', docPath: ['Leadership'] }))).toEqual(['Leadership']);
    expect(notePath(note({ title: 'a', source: 'confluence', sourceDetail: 'ENG' }))).toEqual(['ENG']);
    expect(notePath(note({ title: 'a', source: 'notes' }))).toEqual([]);
  });

  it('drops blank segments', () => {
    expect(notePath(note({ title: 'a', source: 'obsidian', docPath: ['', 'Daily'] }))).toEqual(['Daily']);
  });
});

describe('buildSourcesTree', () => {
  const notes = [
    note({ title: 'ADR-24 Outbox', source: 'confluence', sourceDetail: 'ENG' }),
    note({ title: 'ADR-9 Sidekiq', source: 'confluence', sourceDetail: 'ENG' }),
    note({ title: 'Runbook', source: 'confluence', sourceDetail: 'PLAT' }),
    note({ title: 'Leadership', source: 'notion' }),
    note({ title: 'Board Update', source: 'notion', docPath: ['Leadership'] }),
    note({ title: '2026-10-09', source: 'obsidian', docPath: ['Daily'] }),
    note({ title: 'Loose note', source: 'obsidian' }),
  ];
  const tree = buildSourcesTree(notes);

  it('orders sources by size, largest first', () => {
    expect(tree.map((r) => r.source)).toEqual(['confluence', 'notion', 'obsidian']);
    expect(tree.map((r) => r.count)).toEqual([3, 2, 2]);
  });

  it('sorts groups and notes numerically within a container', () => {
    const eng = tree[0].children[0] as SourceTreeGroup;
    expect(eng.label).toBe('ENG');
    expect(eng.children.map((c) => (c.kind === 'note' ? c.note.title : c.label))).toEqual([
      'ADR-9 Sidekiq',
      'ADR-24 Outbox',
    ]);
  });

  it('folds a parent page into its container group', () => {
    const notion = tree[1];
    expect(notion.children).toHaveLength(1);
    const leadership = notion.children[0] as SourceTreeGroup;
    expect(leadership.kind).toBe('group');
    expect(leadership.note?.title).toBe('Leadership');
    expect(leadership.count).toBe(2);
    expect(leadership.children).toHaveLength(1);
  });

  it('lists containers before loose notes', () => {
    const obsidian = tree[2];
    expect(obsidian.children.map((c) => c.kind)).toEqual(['group', 'note']);
  });

  it('keeps a "/" in a title from colliding with a nested path', () => {
    const t = buildSourcesTree([
      note({ title: 'a', source: 'notion', docPath: ['Q3/Q4'] }),
      note({ title: 'b', source: 'notion', docPath: ['Q3', 'Q4'] }),
    ]);
    const keys = t[0].children.map((c) => c.key);
    expect(new Set(keys).size).toBe(2);
  });

  it('builds unique keys', () => {
    const keys: string[] = [];
    const walk = (nodes: typeof tree[number]['children']) => {
      for (const n of nodes) {
        keys.push(n.key);
        if (n.kind === 'group') walk(n.children);
      }
    };
    tree.forEach((r) => { keys.push(r.key); walk(r.children); });
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('finds the group trail to a note', () => {
    const board = notes[4];
    expect(pathKeysTo(tree, board.id)).toEqual(['src:notion', 'src:notion\u001fLeadership']);
    expect(pathKeysTo(tree, 'missing')).toBeNull();
  });
});

describe('filterSourcesTree', () => {
  const tree = buildSourcesTree([
    note({ title: 'ACH Cut-over Plan', source: 'confluence', sourceDetail: 'PLAT' }),
    note({ title: 'SOC 2 Overview', source: 'confluence', sourceDetail: 'SEC' }),
    note({ title: 'Ideas', source: 'notes' }),
  ]);

  it('returns everything for an empty query', () => {
    expect(filterSourcesTree(tree, '  ').roots).toHaveLength(2);
  });

  it('keeps only matching notes and opens their containers', () => {
    const { roots, openKeys } = filterSourcesTree(tree, 'cut-over');
    expect(roots).toHaveLength(1);
    expect(roots[0].count).toBe(1);
    expect([...openKeys].sort()).toEqual(['src:confluence', 'src:confluence\u001fPLAT']);
  });
});
