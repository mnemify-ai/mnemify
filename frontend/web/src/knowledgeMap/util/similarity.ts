// Tag→region weights are cosine similarities in [0, 1]. Users read a
// percentage more readily than a two-decimal fraction (issue #15), and it
// matches the width of the similarity bar drawn beside the number.

export function similarityPercent(weight: number): number {
  return Math.round(Math.max(0, Math.min(1, weight)) * 100);
}

export function formatSimilarity(weight: number): string {
  return `${similarityPercent(weight)}%`;
}
