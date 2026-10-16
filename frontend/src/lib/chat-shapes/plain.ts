/**
 * 部品（```openui-lang の `root = 部品(...)`）を、部品を描けない画面のために読める文章にする。
 *
 * 使う所:
 * - スマホのアプリ（mobile/chat-markdown.tsx）: 同じ部屋の履歴を読むが部品の描画が無いので、
 *   表は Markdown の表、選択肢と入力欄は番号つきの文章、手順は番号つきの行、グラフは数字の行にする。
 *   mobile/chat-shapes-plain.ts はこのファイルと同じ中身（アプリは別のパッケージなので取り込めない。
 *   両方を同じに保つ。tests/chat_shapes_plain.test.mjs が同じ出力になることを見る）。
 *
 * OpenUI Lang の引数（文字列・数値・配列・{name: "x", values: [...]} の形の物）を読む小さな読み手を
 * 持つ。lang-core には依存しない（アプリに入れないため）。読めない時は null を返し、呼び出し側は
 * 元のコードのまま出す。
 */

export type ShapeCall = { name: string; args: unknown[] };

class Reader {
  i = 0;
  s: string;
  constructor(s: string) { this.s = s; }
  ws() { while (this.i < this.s.length && /\s/.test(this.s[this.i])) this.i++; }
  peek() { return this.s[this.i]; }
  eat(c: string) { this.ws(); if (this.s[this.i] !== c) throw new Error(`expected ${c}`); this.i++; }
  value(): unknown {
    this.ws();
    const c = this.peek();
    if (c === '"' || c === "'") return this.str(c);
    if (c === '[') return this.arr();
    if (c === '{') return this.obj();
    const m = this.s.slice(this.i).match(/^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?/i);
    if (m) { this.i += m[0].length; return Number(m[0]); }
    const w = this.s.slice(this.i).match(/^[A-Za-z_][A-Za-z0-9_]*/);
    if (w) {
      this.i += w[0].length;
      if (w[0] === 'true') return true;
      if (w[0] === 'false') return false;
      if (w[0] === 'null') return null;
      throw new Error(`unexpected ${w[0]}`);
    }
    throw new Error('unexpected');
  }
  str(q: string): string {
    this.i++;
    let out = '';
    while (this.i < this.s.length) {
      const c = this.s[this.i++];
      if (c === '\\') {
        const n = this.s[this.i++];
        out += n === 'n' ? '\n' : n === 't' ? '\t' : (n ?? '');
        continue;
      }
      if (c === q) return out;
      out += c;
    }
    throw new Error('unterminated string');
  }
  arr(): unknown[] {
    this.eat('[');
    const out: unknown[] = [];
    for (;;) {
      this.ws();
      if (this.peek() === ']') { this.i++; return out; }
      out.push(this.value());
      this.ws();
      if (this.peek() === ',') { this.i++; continue; }
      if (this.peek() === ']') { this.i++; return out; }
      throw new Error('bad array');
    }
  }
  obj(): Record<string, unknown> {
    this.eat('{');
    const out: Record<string, unknown> = {};
    for (;;) {
      this.ws();
      if (this.peek() === '}') { this.i++; return out; }
      let key: string;
      if (this.peek() === '"' || this.peek() === "'") key = this.str(this.peek());
      else {
        const w = this.s.slice(this.i).match(/^[A-Za-z_][A-Za-z0-9_]*/);
        if (!w) throw new Error('bad key');
        key = w[0]; this.i += w[0].length;
      }
      this.eat(':');
      out[key] = this.value();
      this.ws();
      if (this.peek() === ',') { this.i++; continue; }
      if (this.peek() === '}') { this.i++; return out; }
      throw new Error('bad object');
    }
  }
}

/** `root = Name(arg, arg, ...)` を読む。読めなければ null。 */
export function parseShapeCall(code: string): ShapeCall | null {
  const m = code.trim().match(/^root\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(([\s\S]*)\)\s*$/);
  if (!m) return null;
  const r = new Reader(m[2]);
  const args: unknown[] = [];
  try {
    for (;;) {
      r.ws();
      if (r.i >= r.s.length) break;
      args.push(r.value());
      r.ws();
      if (r.peek() === ',') { r.i++; continue; }
      if (r.i >= r.s.length) break;
      return null;
    }
  } catch {
    return null;
  }
  return { name: m[1], args };
}

const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []);
const str = (v: unknown): string => (typeof v === 'string' ? v : '');
const cell = (s: string) => s.replace(/\|/g, '｜').replace(/\n/g, ' ');

/**
 * 部品を読める文章（Markdown）にする。読めない・知らない部品なら null（呼び出し側は元のコードのまま）。
 * 選択肢・入力欄には「答えはチャットで」と添える（アプリでは押せない）。
 */
export function shapeToPlainMarkdown(code: string): string | null {
  const call = parseShapeCall(code);
  if (!call) return null;
  const [a0, a1, a2, a3, a4] = call.args;
  switch (call.name) {
    case 'Compare': {
      const columns = strs(a0);
      const rows = Array.isArray(a1) ? a1.map(strs) : [];
      if (columns.length === 0 || rows.length === 0) return null;
      const head = `| ${columns.map(cell).join(' | ')} |`;
      const rule = `|${columns.map(() => '---').join('|')}|`;
      const body = rows.map((r) => `| ${columns.map((_, i) => cell(r[i] ?? '')).join(' | ')} |`);
      return [...(str(a2) ? [`**${str(a2)}**`, ''] : []), head, rule, ...body].join('\n');
    }
    case 'Choice': {
      const q = str(a0);
      const options = strs(a1);
      if (!q || options.length === 0) return null;
      return [`**${q}**`, ...options.map((o, i) => `${i + 1}. ${o}`), '', `（この画面では押せません。番号か選択肢の文字をそのまま送ってください: 「${q} → …」）`].join('\n');
    }
    case 'Input': {
      const label = str(a0);
      if (!label) return null;
      const kind = str(a1);
      const unit = str(a2);
      const placeholder = str(a3).replace(/^例\s*[:：]\s*/, '');   // 入力例に「例: 」が付いていても二重にしない
      const what = kind === 'number' ? `数値${unit ? `（${unit}）` : ''}` : '短い文';
      return [`**${label}**: ${what}を1つ送ってください${placeholder ? `（例: ${placeholder}）` : ''}。`, `（この画面では入力欄は出ません。「${label} → …」の形で送ると分かりやすいです）`].join('\n');
    }
    case 'Steps': {
      const steps = strs(a0);
      if (steps.length === 0) return null;
      return [...(str(a1) ? [`**${str(a1)}**`] : []), ...steps.map((s, i) => `${i + 1}. ${s}`)].join('\n');
    }
    case 'Chart': {
      const labels = strs(a1);
      const series = Array.isArray(a2)
        ? a2
            .filter((s): s is { name?: unknown; values?: unknown } => !!s && typeof s === 'object')
            .map((s) => ({ name: str(s.name), values: Array.isArray(s.values) ? s.values.map((v) => (typeof v === 'number' ? v : NaN)) : [] }))
        : [];
      if (labels.length === 0 || series.length === 0) return null;
      const unit = str(a3);
      const title = str(a4) || (str(a0) === 'line' ? '推移' : '比較');
      const fmt = (v: number) => (Number.isFinite(v) ? `${v.toLocaleString('ja-JP')}${unit}` : '—');
      const head = `| | ${series.map((s) => cell(s.name || '値')).join(' | ')} |`;
      const rule = `|---|${series.map(() => '---').join('|')}|`;
      const body = labels.map((l, i) => `| ${cell(l)} | ${series.map((s) => fmt(s.values[i])).join(' | ')} |`);
      return [`**${title}**`, '', head, rule, ...body].join('\n');
    }
    default:
      return null;
  }
}

/**
 * 返事の本文の中の ```openui-lang ブロックを読める文章に置き換える（部品を描けない画面用）。
 * フェンスの読み方は split.ts と同じ決まり（字下げ3つまで、``` か ~~~、閉じは同じ文字で本数以上）。
 * 読めないブロックはそのまま残す。
 */
export function replaceShapeBlocks(text: string): string {
  if (!/(^|\n) {0,3}(`{3,}|~{3,})[ \t]*(openui-lang|openui)(?=[ \t\r\n]|$)/i.test(text)) return text;
  const lines = text.split('\n');
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i].replace(/\r$/, '');
    const m = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    const open = m && !(m[1][0] === '`' && m[2].includes('`')) ? { char: m[1][0], size: m[1].length, lang: (m[2].trim().split(/\s+/)[0] || '').toLowerCase() } : null;
    if (!open) { out.push(lines[i]); i++; continue; }
    let j = i + 1;
    const body: string[] = [];
    let closed = false;
    while (j < lines.length) {
      const cm = lines[j].replace(/\r$/, '').match(/^ {0,3}(`{3,}|~{3,})[ \t]*$/);
      if (cm && cm[1][0] === open.char && cm[1].length >= open.size) { closed = true; break; }
      body.push(lines[j].replace(/\r$/, ''));
      j++;
    }
    const isShape = open.lang === 'openui-lang' || open.lang === 'openui';
    const plain = isShape && closed ? shapeToPlainMarkdown(body.join('\n')) : null;
    if (plain) {
      out.push(plain);
      i = j + 1;
      continue;
    }
    out.push(...lines.slice(i, closed ? j + 1 : j));
    i = closed ? j + 1 : j;
  }
  return out.join('\n');
}
