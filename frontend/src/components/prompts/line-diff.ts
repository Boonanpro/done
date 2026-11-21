// 2つの文の行ごとの違い（ダンが直した所・保存していない書きかけを見せる。2026-11-21）。指示文は数百行までなので、素直な LCS で足りる。
export type DiffRow = { kind: 'same' | 'add' | 'del'; text: string; line: number };   // line: 新しい方の行番号（del は直前の行）

export function lineDiff(before: string, after: string): DiffRow[] {
  const a = before.split('\n'), b = after.split('\n');
  const n = a.length, m = b.length;
  if (n * m > 4_000_000) {   // 大きすぎる時は全部入れ替えとして見せる
    return [...a.map((text, i) => ({ kind: 'del' as const, text, line: i })), ...b.map((text, i) => ({ kind: 'add' as const, text, line: i + 1 }))];
  }
  const dp: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: DiffRow[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ kind: 'same', text: b[j], line: j + 1 }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ kind: 'del', text: a[i], line: j }); i++; }
    else { out.push({ kind: 'add', text: b[j], line: j + 1 }); j++; }
  }
  while (i < n) { out.push({ kind: 'del', text: a[i], line: j }); i++; }
  while (j < m) { out.push({ kind: 'add', text: b[j], line: j + 1 }); j++; }
  return out;
}

/** 違う所と前後 ctx 行だけ。間の同じ行は { gap } で縮める */
export function hunks(rows: DiffRow[], ctx = 1): (DiffRow | { gap: number })[] {
  const keep = new Set<number>();
  rows.forEach((r, i) => { if (r.kind !== 'same') for (let k = i - ctx; k <= i + ctx; k++) keep.add(k); });
  const out: (DiffRow | { gap: number })[] = [];
  let gap = 0;
  rows.forEach((r, i) => {
    if (keep.has(i)) { if (gap) out.push({ gap }); gap = 0; out.push(r); } else gap++;
  });
  if (gap && out.length) out.push({ gap });
  return out;
}

/** ダンに渡す短い違い（- 消した行 / + 足した行、行番号つき） */
export function diffText(before: string, after: string, max = 80): string {
  const rows = lineDiff(before, after).filter(r => r.kind !== 'same');
  const lines = rows.slice(0, max).map(r => `${r.kind === 'add' ? '+' : '-'} ${r.line}: ${r.text}`);
  if (rows.length > max) lines.push(`…ほか${rows.length - max}行`);
  return lines.join('\n');
}
