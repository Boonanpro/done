// スマホのアプリ用: ダンの返事の中の部品（```openui-lang）を読める文章にする。
// frontend/src/lib/chat-shapes/plain.ts と同じ中身（アプリは別のパッケージなので取り込めない。両方を同じに保つ。
// tests/chat_shapes_plain.test.mjs が両方の出力が同じことを見る）。
/**
 * 部品（```openui-lang の `root = 部品(...)`）を、部品を描けない画面のために読める文章にする。
 * あわせて、返事の本文の中からコードブロックを見つける読み手（scanBlocks）を持つ。split.ts も同じ読み手を使う。
 *
 * 使う所:
 * - スマホのアプリ（mobile/chat-markdown.tsx）: 同じ部屋の履歴を読むが部品の描画が無いので、
 *   表は Markdown の表、選択肢と入力欄は番号つきの文章、手順は番号つきの行、グラフは数字の行にする。
 *   mobile/chat-shapes-plain.ts はこのファイルと同じ中身（アプリは別のパッケージなので取り込めない。
 *   両方を同じに保つ。tests/chat_shapes_plain.test.mjs が同じ出力になることを見る）。
 * - 画面の切り出し（split.ts）: どの行がコードブロックで、どれが HTML ブロックかの判定をここから借りる。
 *
 * コードブロックの見つけ方は Markdown（CommonMark）のとおり:
 * - 開きは行頭（字下げ3つまで）の ``` か ~~~（3つ以上）。情報文字列の最初の語が言語名。
 *   バッククォートのフェンスの情報文字列にバッククォートは書けない
 * - 閉じは同じ文字で開きと同じ本数以上、後ろは空白だけ。行末の CR（CRLF）は無視する
 * - HTML ブロック（<!-- コメント -->、<pre>/<script>/<style>/<textarea>、<div> などのブロック要素、
 *   空行の後の単独のタグ）の中はフェンスとして読まない。コメントの中に書かれた部品はコメントの一部
 *   （部品にしない・書き換えない）。引用（> ```）は行頭が > なので最初からフェンスではない
 *
 * 文字列の読み方は OpenUI Lang（lang-core）と同じ規則:
 * - "..." は JSON の文字列。エスケープは \" \\ \/ \b \f \n \r \t \uXXXX だけ。JSON に無いエスケープや
 *   生の制御文字は「読めない」とし（null）、呼び出し側は元のブロックをそのまま残す。別の文字列に黙って変えない
 *   （lang-core はその場合バックスラッシュごと生の文字を見せる。見え方の違いは試験で固定）
 * - '...' は lang-core の独自規則: \' \\ \n \t だけ、それ以外はバックスラッシュを落として次の文字
 *
 * lang-core には依存しない（アプリに入れないため）。
 */

export type ShapeCall = { name: string; args: unknown[] };

// --- コードブロック・HTML ブロックの読み手（split.ts と共有） ------------------------------------

export type FenceInfo = { char: '`' | '~'; size: number; lang: string };

export type ScannedBlock =
  /** lines[start, end) は HTML ブロック（文章側のまま。中のフェンスはフェンスではない） */
  | { kind: 'html'; start: number; end: number }
  /** lines[start, end) はコードブロック。end は閉じ行の次（閉じが無ければ末尾）。body は中身（行末 CR 抜き） */
  | { kind: 'fence'; start: number; end: number; closed: boolean; fence: FenceInfo; body: string[] };

const SHAPE_FENCE_LANGS = new Set(['openui-lang', 'openui']);

/** その言語名のコードブロックが部品か（openui-lang / openui）。 */
export function isShapeLang(lang: string): boolean {
  return SHAPE_FENCE_LANGS.has(lang);
}

/** 速い前判定: 部品のフェンスの開き行らしき物があるか（本当の判定は scanBlocks）。 */
export const SHAPE_FENCE_RE = /(^|\n) {0,3}(`{3,}|~{3,})[ \t]*(openui-lang|openui)(?=[ \t\r\n]|$)/i;

const stripCr = (line: string) => line.replace(/\r$/, '');

/** フェンスの開き行なら { char, size, lang }。lang は情報文字列の最初の語（小文字。無ければ ''）。 */
export function fenceOpen(rawLine: string): FenceInfo | null {
  const line = stripCr(rawLine);
  const m = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
  if (!m) return null;
  const char = m[1][0] as '`' | '~';
  const info = m[2];
  // CommonMark: バッククォートのフェンスの情報文字列にバッククォートは含められない（その行は開きではない）
  if (char === '`' && info.includes('`')) return null;
  const lang = (info.trim().split(/\s+/)[0] || '').toLowerCase();
  return { char, size: m[1].length, lang };
}

/** 閉じ行: 開きと同じ文字で本数が同じか多く、後ろは空白だけ。 */
export function fenceClose(rawLine: string, open: FenceInfo): boolean {
  const m = stripCr(rawLine).match(/^ {0,3}(`{3,}|~{3,})[ \t]*$/);
  return !!m && m[1][0] === open.char && m[1].length >= open.size;
}

// CommonMark 4.6 HTML blocks。種類1〜5は終わりの印が出る行まで、6〜7は空行まで。7だけは段落の途中では始まらない
const HTML_RAW_START = /^<(script|pre|style|textarea)(?=[\s>]|$)/i;
const HTML_RAW_END = /<\/(script|pre|style|textarea)>/i;
const HTML_BLOCK_TAGS = new Set([
  'address', 'article', 'aside', 'base', 'basefont', 'blockquote', 'body', 'caption', 'center', 'col', 'colgroup', 'dd',
  'details', 'dialog', 'dir', 'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer', 'form', 'frame', 'frameset',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'head', 'header', 'hr', 'html', 'iframe', 'legend', 'li', 'link', 'main', 'menu',
  'menuitem', 'nav', 'noframes', 'ol', 'optgroup', 'option', 'p', 'param', 'search', 'section', 'summary', 'table', 'tbody',
  'td', 'tfoot', 'th', 'thead', 'title', 'tr', 'track', 'ul',
]);
const HTML_TAG_START = /^<\/?([A-Za-z][A-Za-z0-9-]*)(?=[\s>]|\/>|$)/;
const HTML_OPEN_TAG = /^<[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z_:][A-Za-z0-9_.:-]*(?:\s*=\s*(?:[^\s"'=<>`]+|'[^']*'|"[^"]*"))?)*\s*\/?>\s*$/;
const HTML_CLOSE_TAG = /^<\/[A-Za-z][A-Za-z0-9-]*\s*>\s*$/;

type HtmlEnd = { until: RegExp } | { untilBlank: true };

function htmlBlockStart(line: string, afterBlank: boolean): HtmlEnd | null {
  const t = line.replace(/^ {0,3}/, '');
  if (t[0] !== '<') return null;
  if (HTML_RAW_START.test(t)) return { until: HTML_RAW_END };
  if (t.startsWith('<!--')) return { until: /-->/ };
  if (t.startsWith('<?')) return { until: /\?>/ };
  if (t.startsWith('<![CDATA[')) return { until: /\]\]>/ };
  if (/^<![A-Za-z]/.test(t)) return { until: />/ };
  const m = t.match(HTML_TAG_START);
  if (m && HTML_BLOCK_TAGS.has(m[1].toLowerCase())) return { untilBlank: true };
  if (afterBlank && (HTML_OPEN_TAG.test(t) || HTML_CLOSE_TAG.test(t))) return { untilBlank: true };
  return null;
}

/**
 * 本文の行の並びから、コードブロックと HTML ブロックを順に見つける。
 * 返す区間は重ならない。区間の外の行は普通の文章。
 */
export function scanBlocks(lines: readonly string[]): ScannedBlock[] {
  const out: ScannedBlock[] = [];
  const n = lines.length;
  let i = 0;
  let afterBlank = true;   // 文書の先頭は「空行の後」と同じ
  while (i < n) {
    const line = stripCr(lines[i]);
    const html = htmlBlockStart(line, afterBlank);
    if (html) {
      let j = i;
      if ('until' in html) {
        // 終わりの印がある行まで含める（最初の行にあればその1行。無ければ末尾まで）
        while (j < n && !html.until.test(stripCr(lines[j]))) j++;
        j = Math.min(j + 1, n);
        afterBlank = false;
      } else {
        j = i + 1;
        while (j < n && stripCr(lines[j]).trim() !== '') j++;
        afterBlank = true;   // 次は空行（か末尾）
      }
      out.push({ kind: 'html', start: i, end: j });
      i = j;
      continue;
    }
    const open = fenceOpen(line);
    if (open) {
      const body: string[] = [];
      let j = i + 1;
      let closed = false;
      while (j < n) {
        if (fenceClose(lines[j], open)) { closed = true; break; }
        body.push(stripCr(lines[j]));
        j++;
      }
      out.push({ kind: 'fence', start: i, end: closed ? j + 1 : j, closed, fence: open, body });
      i = closed ? j + 1 : j;
      afterBlank = false;
      continue;
    }
    afterBlank = line.trim() === '';
    i++;
  }
  return out;
}

// --- OpenUI Lang の引数の読み手 ------------------------------------------------------------------

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
  /** 文字列。"..." は JSON の規則（読めないエスケープは例外）、'...' は lang-core の独自規則。 */
  str(q: string): string {
    this.i++;
    let out = '';
    while (this.i < this.s.length) {
      const c = this.s[this.i++];
      if (c === q) return out;
      if (c !== '\\') {
        if (q === '"' && c.charCodeAt(0) < 0x20) throw new Error('control character in string');
        out += c;
        continue;
      }
      const n = this.s[this.i++];
      if (n === undefined) break;
      if (q === "'") {
        out += n === 'n' ? '\n' : n === 't' ? '\t' : n;   // \' と \\ はその文字のまま
        continue;
      }
      switch (n) {
        case '"': case '\\': case '/': out += n; break;
        case 'b': out += '\b'; break;
        case 'f': out += '\f'; break;
        case 'n': out += '\n'; break;
        case 'r': out += '\r'; break;
        case 't': out += '\t'; break;
        case 'u': {
          const hex = this.s.slice(this.i, this.i + 4);
          if (!/^[0-9a-fA-F]{4}$/.test(hex)) throw new Error('bad unicode escape');
          out += String.fromCharCode(parseInt(hex, 16));
          this.i += 4;
          break;
        }
        default:
          throw new Error(`unknown escape \\${n}`);
      }
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

// --- 読める文章にする ------------------------------------------------------------------------------

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
 * ブロックの見つけ方は scanBlocks（split.ts と同じ）。HTML ブロック（コメントなど）の中は触らない。
 * 読めないブロックはそのまま残す。
 */
export function replaceShapeBlocks(text: string): string {
  if (!SHAPE_FENCE_RE.test(text)) return text;
  const lines = text.split('\n');
  const out: string[] = [];
  let i = 0;
  for (const b of scanBlocks(lines)) {
    out.push(...lines.slice(i, b.start));
    const plain = b.kind === 'fence' && b.closed && isShapeLang(b.fence.lang) ? shapeToPlainMarkdown(b.body.join('\n')) : null;
    if (plain !== null) out.push(plain);
    else out.push(...lines.slice(b.start, b.end));
    i = b.end;
  }
  out.push(...lines.slice(i));
  return out.join('\n');
}
