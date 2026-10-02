// 本文を段落・見出し・表に分ける（画面の部品を含まない純粋な処理。chat-markdown.tsx が使う）。

export type MdBlock =
  | { kind: 'text'; text: string }
  | { kind: 'heading'; text: string }
  | { kind: 'table'; header: string[]; rows: string[][] };

const TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function cells(line: string): string[] {
  let s = line.trim();
  if (s.startsWith('|')) s = s.slice(1);
  if (s.endsWith('|')) s = s.slice(0, -1);
  return s.split('|').map((c) => c.trim());
}

/** 本文を段落・見出し・表に分ける。表は「| 見出し |」の行の次に「|---|」の行があるもの。 */
export function splitMarkdownBlocks(text: string): MdBlock[] {
  const lines = text.split('\n');
  const blocks: MdBlock[] = [];
  let para: string[] = [];
  const flush = () => {
    const t = para.join('\n').replace(/^\n+|\n+$/g, '');
    if (t) blocks.push({ kind: 'text', text: t });
    para = [];
  };
  let inCode = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim().startsWith('```')) {
      inCode = !inCode;
      para.push(line);
      continue;
    }
    if (!inCode && line.trim().startsWith('|') && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1])) {
      flush();
      const header = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(cells(lines[i]));
        i++;
      }
      i--;
      blocks.push({ kind: 'table', header, rows });
      continue;
    }
    const heading = !inCode && line.match(/^\s{0,3}#{1,6}\s+(.*)$/);
    if (heading) {
      flush();
      blocks.push({ kind: 'heading', text: heading[1].replace(/\s+#+\s*$/, '') });
      continue;
    }
    para.push(line);
  }
  flush();
  return blocks;
}

/** 文中のリンク [文字](URL) を分ける。 */
export function splitLinks(text: string): Array<{ kind: 'text'; value: string } | { kind: 'link'; label: string; url: string }> {
  const out: Array<{ kind: 'text'; value: string } | { kind: 'link'; label: string; url: string }> = [];
  const pattern = /\[([^\]]+)\]\(([^)]+)\)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) out.push({ kind: 'text', value: text.slice(last, m.index) });
    out.push({ kind: 'link', label: m[1], url: m[2] });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ kind: 'text', value: text.slice(last) });
  return out;
}
