const ROMAN: ReadonlyArray<readonly [number, string]> = [
  [1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'],
  [100, 'C'],  [90, 'XC'],  [50, 'L'],  [40, 'XL'],
  [10, 'X'],   [9, 'IX'],   [5, 'V'],   [4, 'IV'],
  [1, 'I'],
];

export function toRoman(n: number): string {
  if (n <= 0) return '';
  let remaining = Math.floor(n);
  let out = '';
  for (const [value, glyph] of ROMAN) {
    while (remaining >= value) {
      out += glyph;
      remaining -= value;
    }
  }
  return out;
}
