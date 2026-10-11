import { describe, expect, it } from 'vitest';
import { formatSimilarity, similarityPercent } from './similarity';

describe('formatSimilarity', () => {
  it('renders a cosine weight as a whole percentage', () => {
    expect(formatSimilarity(0.72)).toBe('72%');
    expect(formatSimilarity(0.456)).toBe('46%');
    expect(formatSimilarity(1)).toBe('100%');
  });

  it('clamps out-of-range weights', () => {
    expect(formatSimilarity(1.2)).toBe('100%');
    expect(formatSimilarity(-0.1)).toBe('0%');
  });

  it('matches the bar width percentage', () => {
    expect(similarityPercent(0.333)).toBe(33);
  });
});
