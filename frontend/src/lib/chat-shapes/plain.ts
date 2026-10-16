/**
 * 部品（```openui-lang の `root = 部品(...)`）を、部品を描けない画面のために読める文章にする。
 * あわせて、返事の本文の中から部品のコードブロックを見つける読み手（topLevelFences）を持つ。split.ts もこれを使う。
 *
 * 使う所:
 * - スマホのアプリ（mobile/chat-markdown.tsx）: 同じ部屋の履歴を読むが部品の描画が無いので、
 *   表は Markdown の表、選択肢と入力欄は番号つきの文章、手順は番号つきの行、グラフは数字の行にする。
 *   mobile/chat-shapes-plain.ts はこのファイルと同じ中身（アプリは別のパッケージなので取り込めない。
 *   両方を同じに保つ。tests/chat_shapes_plain.test.mjs が同じ出力になることを見る）。
 * - 画面の切り出し（split.ts）: どこからどこまでが部品のコードブロックかをここから借りる。
 * - サーバー（app/agent/chat_shapes.py）は同じ手順の Python の写しで部品の鍵を作り直す（答えの照合）。
 *
 * 部品は「文書の一番外側（引用・箇条書きの中ではない）にある、言語名が openui-lang か openui のコードブロック
 * （``` か ~~~）」。どこからどこまでがそれかは、Web の文章の描画（react-markdown）が使う Markdown の読み手
 * remark-parse（micromark）と同じ手順で決める。CommonMark の仕様書の文面ではなく micromark の実際の手順を写した
 * （仕様書と違う所がある: 遅延継続の行の単独タグ、<pre/>、字下げコードと空行の後の「2)」など。
 * tests/chat_shapes_markdown.test.mjs が remark-parse の構文木と突き合わせる）。決まりは:
 * - 行の区切りは \n・\r\n・\r。文書の先頭の BOM は読まない。NUL は U+FFFD として読む
 * - 空白は半角スペースとタブだけ。NBSP・全角空白・NEL・BOM・U+2028 などは空白ではなく、ふつうの文字。
 *   タブは次の4の倍数の列まで進む（字下げは列で数える）。空行は空白だけの行
 * - 入れ物（引用 > と、箇条書き - + * と 1. 1)）の中のコードブロックは一番外側ではない。入れ物の続きの行
 *   （> や字下げの無い行）は、段落の続きの時だけ入れ物の中に残る（遅延継続）
 * - 段落の途中で始まれる物: 見出し #、区切り線、Setext の下線（=== ---。遅延継続の行では始まれない）、
 *   HTML ブロックの種類1〜6、フェンス。始まれない物: 字下げコード（4列以上）、HTML の種類7（単独の完全な
 *   タグ）。ただし種類7は遅延継続の行では段落を切る（micromark の手順。その HTML は入れ物の中に残る）
 * - HTML ブロック: 1 <script|pre|style|textarea（後ろが空白・> ・行末。終わりは </その4つのどれか>）、
 *   2 <!--（-->）、3 <?（?>）、4 <! と英字（>）、5 <![CDATA[（]]>）、6 ブロック要素の名前（空行まで）、
 *   7 単独の完全な開きタグか閉じタグ（後ろは空白だけ。空行まで。名前の制限は micromark のとおり <pre/> も入る）。
 *   1〜5 は終わりの印のある行まで（開きの行にあればその1行）。どれも遅延継続の行が来たら終わる
 * - フェンス: 字下げ3列まで、` か ~ が3つ以上。言語名は情報文字列の最初の語（空白まで）で、バックスラッシュの
 *   エスケープと数値の文字参照を解く（名前の文字参照で英小文字と - になる物は無いので解かない）。大文字小文字は
 *   区別する。` のフェンスの行に ` があれば開きではない。閉じは同じ文字で開き以上の本数、字下げ3列まで、
 *   後ろは空白だけ。中身は各行の先頭から開きの字下げの列数まで空白を外す。改行は元のまま（\r\n も）
 *
 * 文字列の読み方は OpenUI Lang（lang-core）と同じ規則:
 * - "..." は JSON の文字列。エスケープは \" \\ \/ \b \f \n \r \t \uXXXX だけ。JSON に無いエスケープや
 *   生の制御文字は「読めない」とし（null）、呼び出し側は元のブロックをそのまま残す。別の文字列に黙って変えない
 *   （lang-core はその場合バックスラッシュごと生の文字を見せる。見え方の違いは試験で固定）
 * - '...' は lang-core の独自規則: \' \\ \n \t だけ、それ以外はバックスラッシュを落として次の文字
 *
 * lang-core にも remark にも依存しない（アプリに入れないため）。
 */

export type ShapeCall = { name: string; args: unknown[] };

// --- Markdown の読み手: 一番外側のコードブロック（micromark と同じ手順。chat_shapes.py に同じ手順の写し） ---

/** 一番外側のコードブロック。位置は本文の中の文字の位置 */
export type TopFence = {
  /** 開きの行の始まり */
  start: number;
  /** 最後の行（閉じの行。閉じが無ければ中身の最後の行）の中身の終わり（改行の前） */
  end: number;
  /** 次の行の始まり（最後の行に改行が無ければ end と同じ） */
  next: number;
  /** 閉じのフェンスまであるか（無ければ文書の終わりまで） */
  closed: boolean;
  /** 言語名（情報文字列の最初の語。エスケープと数値の文字参照を解いた物） */
  lang: string;
  /** 中身（開きの字下げの列数まで空白を外した各行を、元の改行でつないだ物） */
  code: string;
};

const SHAPE_FENCE_LANGS = new Set(['openui-lang', 'openui']);

/** その言語名のコードブロックが部品か（openui-lang / openui。大文字小文字は区別する）。 */
export function isShapeLang(lang: string): boolean {
  return SHAPE_FENCE_LANGS.has(lang);
}

// 行は1文字ずつの符号の並び。タブは HT の後に次の4の倍数の列まで VS が続く（micromark の前処理と同じ）。
// ほかの文字は UTF-16 の単位の番号。空白は半角スペース・HT・VS だけ
const HT = -2;
const VS = -1;

type MdLine = { codes: number[]; chars: string[]; start: number; end: number; next: number; eol: string };

function readLines(text: string): MdLine[] {
  const lines: MdLine[] = [];
  let i = text.charCodeAt(0) === 0xfeff ? 1 : 0;   // 文書の先頭の BOM は読まない
  while (i < text.length) {
    const start = i;
    const codes: number[] = [];
    const chars: string[] = [];
    let column = 1;
    for (; i < text.length; i++) {
      const c = text.charCodeAt(i);
      if (c === 10 || c === 13) break;
      if (c === 9) {
        const stop = Math.ceil(column / 4) * 4;
        codes.push(HT); chars.push('\t');
        while (column++ < stop) { codes.push(VS); chars.push(''); }
      } else if (c === 0) {
        codes.push(0xfffd); chars.push('\ufffd'); column++;
      } else {
        codes.push(c); chars.push(text[i]); column++;
      }
    }
    const end = i;
    const eol = text.charCodeAt(i) === 13 ? (text.charCodeAt(i + 1) === 10 ? '\r\n' : '\r') : text.charCodeAt(i) === 10 ? '\n' : '';
    i += eol.length;
    lines.push({ codes, chars, start, end, next: i, eol });
  }
  return lines;
}

const isSpace = (c: number | undefined) => c === 32 || c === HT || c === VS;
const isDigit = (c: number | undefined) => c !== undefined && c >= 48 && c <= 57;
const isAlpha = (c: number | undefined) => c !== undefined && ((c >= 65 && c <= 90) || (c >= 97 && c <= 122));
const isAlnum = (c: number | undefined) => isDigit(c) || isAlpha(c);

/** p から続く空白の数（max まで） */
function spaces(L: MdLine, p: number, max = Infinity): number {
  let n = 0;
  while (n < max && isSpace(L.codes[p + n])) n++;
  return n;
}

/** p から行末まで空白だけか */
function blankFrom(L: MdLine, p: number): boolean {
  return p + spaces(L, p) >= L.codes.length;
}

/** p から q までの元の文字。タブの続きの VS は書かない。前のタブの途中から始まる VS は半角スペース */
function slice(L: MdLine, p: number, q = L.codes.length): string {
  let out = '';
  let atTab = false;
  for (let k = p; k < q; k++) {
    const c = L.codes[k];
    if (c === VS) {
      if (atTab) continue;
      out += ' ';
    } else {
      out += L.chars[k];
    }
    atTab = c === HT;
  }
  return out;
}

// フェンスの言語名のエスケープと文字参照（micromark-util-decode-string と同じ範囲）
const ESCAPE_OR_REFERENCE = /\\([!-/:-@[-`{-~])|&(#(?:[0-9]{1,7}|[xX][0-9A-Fa-f]{1,6})|[0-9A-Za-z]{1,31});/g;

function numericReference(n: number): string {
  if (n < 9 || n === 11 || (n > 13 && n < 32) || (n > 126 && n < 160) || (n > 55295 && n < 57344)
    || (n > 64975 && n < 65008) || (n & 65535) === 65535 || (n & 65535) === 65534 || n > 1114111) return '\ufffd';
  return String.fromCodePoint(n);
}

function decodeString(s: string): string {
  return s.replace(ESCAPE_OR_REFERENCE, (all: string, escaped: string | undefined, ref: string | undefined) => {
    if (escaped) return escaped;
    if (ref && ref[0] === '#') {
      const hex = ref[1] === 'x' || ref[1] === 'X';
      return numericReference(parseInt(ref.slice(hex ? 2 : 1), hex ? 16 : 10));
    }
    return all;   // 名前の文字参照（&amp; など）は解かない: 解いても openui-lang の文字（英小文字と -）にはならない
  });
}

/** 区切り線（* - _ が3つ以上、間と後ろは空白だけ） */
function thematicBreakAt(L: MdLine, q: number): boolean {
  const marker = L.codes[q];
  let count = 0;
  let i = q;
  while (i < L.codes.length) {
    if (L.codes[i] === marker) { count++; i++; } else if (isSpace(L.codes[i])) i++; else return false;
  }
  return count >= 3;
}

/** 見出し（# が1〜6個、後ろは空白か行末） */
function atxAt(L: MdLine, q: number): boolean {
  let n = 0;
  while (L.codes[q + n] === 35) n++;
  if (n > 6) return false;
  const after = L.codes[q + n];
  return after === undefined || isSpace(after);
}

/** Setext の下線（= か - だけ、後ろは空白だけ） */
function setextAt(L: MdLine, q: number): boolean {
  const marker = L.codes[q];
  let i = q;
  while (L.codes[i] === marker) i++;
  return blankFrom(L, i);
}

type Fence = { t: 'fence'; marker: number; sizeOpen: number; prefix: number; lang: string; top: boolean; startLine: number; lastLine: number; lines: string[]; eols: string[] };

/** フェンスの開き（q は ` か ~ の位置、prefix は字下げの列数）。開きでなければ null */
function fenceAt(L: MdLine, q: number, prefix: number, line: number): Fence | null {
  const marker = L.codes[q];
  let i = q;
  while (L.codes[i] === marker) i++;
  const sizeOpen = i - q;
  if (sizeOpen < 3) return null;
  i += spaces(L, i);
  const infoStart = i;
  for (; i < L.codes.length && !isSpace(L.codes[i]); i++) if (marker === 96 && L.codes[i] === 96) return null;
  const info = slice(L, infoStart, i);
  for (; i < L.codes.length; i++) if (marker === 96 && L.codes[i] === 96) return null;
  return { t: 'fence', marker, sizeOpen, prefix, lang: decodeString(info), top: false, startLine: line, lastLine: line, lines: [], eols: [] };
}

/** フェンスの閉じ（字下げ3列まで、同じ文字で開き以上の本数、後ろは空白だけ） */
function closesFence(L: MdLine, p: number, f: Fence): boolean {
  let i = p + spaces(L, p, 3);
  if (L.codes[i] !== f.marker) return false;
  let n = 0;
  while (L.codes[i] === f.marker) { i++; n++; }
  return n >= f.sizeOpen && blankFrom(L, i);
}

// HTML ブロック（micromark-core-commonmark html-flow.js の手順）
const HTML_RAW = new Set(['pre', 'script', 'style', 'textarea']);
const HTML_BLOCK = new Set([
  'address', 'article', 'aside', 'base', 'basefont', 'blockquote', 'body', 'caption', 'center', 'col', 'colgroup', 'dd',
  'details', 'dialog', 'dir', 'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer', 'form', 'frame', 'frameset',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'head', 'header', 'hr', 'html', 'iframe', 'legend', 'li', 'link', 'main', 'menu',
  'menuitem', 'nav', 'noframes', 'ol', 'optgroup', 'option', 'p', 'param', 'search', 'section', 'summary', 'table', 'tbody',
  'td', 'tfoot', 'th', 'thead', 'title', 'tr', 'track', 'ul',
]);
const HTML_END: Record<number, RegExp> = {
  1: /<\/(?:script|pre|style|textarea)>/i, 2: /-->/, 3: /\?>/, 4: />/, 5: /\]\]>/,
};

/** 種類7の完全なタグの残り（i はタグ名の次）。後ろは空白だけ */
function completeTag(L: MdLine, i: number, closing: boolean): boolean {
  const c = L.codes;
  if (closing) {
    i += spaces(L, i);
    return c[i] === 62 && blankFrom(L, i + 1);
  }
  let s: 'nameBefore' | 'name' | 'nameAfter' | 'valueBefore' | 'unquoted' | 'quotedAfter' | 'end' = 'nameBefore';
  for (;;) {
    const ch = c[i];
    switch (s) {
      case 'nameBefore':
        if (ch === 47) { i++; s = 'end'; } else if (ch === 58 || ch === 95 || isAlpha(ch)) { i++; s = 'name'; } else if (isSpace(ch)) i++; else s = 'end';
        break;
      case 'name':
        if (ch === 45 || ch === 46 || ch === 58 || ch === 95 || isAlnum(ch)) i++; else s = 'nameAfter';
        break;
      case 'nameAfter':
        if (ch === 61) { i++; s = 'valueBefore'; } else if (isSpace(ch)) i++; else s = 'nameBefore';
        break;
      case 'valueBefore':
        if (ch === undefined || ch === 60 || ch === 61 || ch === 62 || ch === 96) return false;
        if (ch === 34 || ch === 39) {
          i++;
          while (c[i] !== ch) { if (i >= c.length) return false; i++; }
          i++;
          s = 'quotedAfter';
        } else if (isSpace(ch)) i++; else s = 'unquoted';
        break;
      case 'unquoted':
        if (ch === undefined || ch === 34 || ch === 39 || ch === 47 || ch === 60 || ch === 61 || ch === 62 || ch === 96 || isSpace(ch)) s = 'nameAfter'; else i++;
        break;
      case 'quotedAfter':
        if (ch === 47 || ch === 62 || isSpace(ch)) s = 'nameBefore'; else return false;
        break;
      case 'end':
        return ch === 62 && blankFrom(L, i + 1);
    }
  }
}

/**
 * HTML ブロックの始まり（q は < の位置）。種類（1〜7）か、始まらなければ 0。
 * interrupt: 段落の途中か（種類7は遅延継続の行でなければ始まらない）
 */
function htmlAt(L: MdLine, q: number, interrupt: boolean, lazy: boolean): number {
  const c = L.codes;
  let i = q + 1;
  if (c[i] === 33) {
    if (c[i + 1] === 45) return c[i + 2] === 45 ? 2 : 0;
    if (c[i + 1] === 91) return slice(L, i + 2, i + 8) === 'CDATA[' ? 5 : 0;
    return isAlpha(c[i + 1]) ? 4 : 0;
  }
  if (c[i] === 63) return 3;
  const closing = c[i] === 47;
  if (closing) i++;
  if (!isAlpha(c[i])) return 0;
  let name = '';
  while (c[i] === 45 || isAlnum(c[i])) { name += L.chars[i]; i++; }
  const after = c[i];
  if (!(after === undefined || after === 47 || after === 62 || isSpace(after))) return 0;
  const lower = name.toLowerCase();
  if (after !== 47 && !closing && HTML_RAW.has(lower)) return 1;
  if (HTML_BLOCK.has(lower)) return after === 47 ? (c[i + 1] === 62 ? 6 : 0) : 6;
  if (interrupt && !lazy) return 0;
  return completeTag(L, i, closing) ? 7 : 0;
}

// 入れ物（micromark-core-commonmark block-quote.js / list.js の手順）
type Quote = { kind: 'quote' };
type List = { kind: 'list'; ordered: boolean; marker: number; size: number; initialBlankLine: boolean; furtherBlankLines: boolean; closeFlow: boolean };
type Container = Quote | List;

/** 引用の印（前に空白3列まで、> の後ろの空白1つは印に含める）。合えば次の位置、合わなければ -1 */
function quoteAt(L: MdLine, p: number): number {
  const q = p + spaces(L, p, 3);
  if (L.codes[q] !== 62) return -1;
  return isSpace(L.codes[q + 1]) ? q + 2 : q + 1;
}

/** 箇条書きの項目の印。cur は続きの項目（同じ箇条書きの次の項目）を探す時の今の箇条書き */
function listAt(L: MdLine, p: number, cur: List | null, interrupt: boolean): [number, List] | null {
  const initial = spaces(L, p, 3);
  let q = p + initial;
  const prefixStart = q;
  const c = L.codes[q];
  const bullet = c === 42 || c === 43 || c === 45;
  const ordered = cur ? cur.ordered : !bullet;
  if (!ordered) {
    if (cur ? c !== cur.marker : !bullet) return null;
    if ((c === 42 || c === 45) && thematicBreakAt(L, q)) return null;
  } else {
    if (!isDigit(c)) return null;
    if (interrupt && c !== 49) return null;
    let size = 0;
    while (isDigit(L.codes[q]) && ++size < 10) q++;
    const d = L.codes[q];
    if (!((!interrupt || size < 2) && (cur ? d === cur.marker : d === 41 || d === 46))) return null;
  }
  const marker = L.codes[q];
  q++;
  let initialSize = initial;
  let initialBlankLine = false;
  if (blankFrom(L, q)) {
    if (interrupt) return null;   // 空の項目は段落を切れない
    initialBlankLine = true;
    initialSize++;
  } else {
    const w = spaces(L, q, 4);
    if (w >= 1 && !isSpace(L.codes[q + w])) q += w;
    else if (isSpace(L.codes[q])) q += 1;
    else return null;
  }
  return [q, {
    kind: 'list', ordered, marker: cur ? cur.marker : marker, size: initialSize + (q - prefixStart),
    initialBlankLine, furtherBlankLines: false, closeFlow: false,
  }];
}

/** 箇条書きの続き（同じ項目の続き、空行、または同じ箇条書きの次の項目＝closeFlow）。合わなければ -1 */
function listContinue(st: List, L: MdLine, p: number): number {
  st.closeFlow = false;
  if (blankFrom(L, p)) {
    st.furtherBlankLines = st.furtherBlankLines || st.initialBlankLine;
    return p + spaces(L, p, st.size);
  }
  const further = st.furtherBlankLines;
  st.furtherBlankLines = false;
  st.initialBlankLine = false;
  if (!further && isSpace(L.codes[p])) {
    const n = spaces(L, p, st.size);
    if (n === st.size) return p + n;
  }
  st.closeFlow = true;
  const next = listAt(L, p, st, false);
  if (!next) return -1;
  Object.assign(st, next[1], { closeFlow: true });
  return next[0];
}

/** 新しい入れ物の始まり。合えば [次の位置, 入れ物] */
function containerAt(L: MdLine, p: number, interrupt: boolean): [number, Container] | null {
  const c = L.codes[p + spaces(L, p, 3)];
  if (c === 62) return [quoteAt(L, p), { kind: 'quote' }];
  if (c === 42 || c === 43 || c === 45 || isDigit(c)) return listAt(L, p, null, interrupt);
  return null;
}

// リンク参照の定義（micromark definition.js と factory-label / destination / title / whitespace の手順）。
// 段落の中身がこれだけなら、その後の === は Setext の見出しにならない（新しい段落になる）
const EOLC = -4;   // 段落の中身の行の区切り
const isControl = (c: number | undefined) => c !== undefined && (c < 32 || c === 127);

function afterLine(c: number[], i: number): number {
  while (isSpace(c[i])) i++;
  return c[i] === undefined || c[i] === EOLC ? i : -1;
}

function definitionAt(c: number[], i: number): number {
  if (c[i] !== 91) return -1;
  i++;
  let size = 0;
  let seen = false;
  for (;;) {
    const ch = c[i];
    if (size > 999 || ch === undefined || ch === 91 || (ch === 93 && !seen)) return -1;
    if (ch === 93) { i++; break; }
    if (ch === EOLC) { i++; continue; }
    for (;;) {
      const d = c[i];
      if (d === undefined || d === 91 || d === 93 || d === EOLC || size++ > 999) break;
      i++;
      if (!seen) seen = !isSpace(d);
      if (d === 92 && (c[i] === 91 || c[i] === 92 || c[i] === 93)) { i++; size++; }
    }
  }
  if (c[i] !== 58) return -1;
  i++;
  while (c[i] === EOLC || isSpace(c[i])) i++;
  if (c[i] === 60) {
    i++;
    for (;;) {
      const d = c[i];
      if (d === 62) { i++; break; }
      if (d === undefined || d === 60 || d === EOLC) return -1;
      i++;
      if (d === 92 && (c[i] === 60 || c[i] === 62 || c[i] === 92)) i++;
    }
  } else {
    if (c[i] === undefined || c[i] === 32 || c[i] === 41 || isControl(c[i])) return -1;
    let balance = 0;
    for (;;) {
      const d = c[i];
      if (!balance && (d === undefined || d === 41 || d === EOLC || isSpace(d))) break;
      if (d === 40) { i++; balance++; continue; }
      if (d === 41) { i++; balance--; continue; }
      if (d === undefined || d === 32 || isControl(d)) return -1;
      i++;
      if (d === 92 && (c[i] === 40 || c[i] === 41 || c[i] === 92)) i++;
    }
  }
  const afterDestination = i;
  if (c[i] === EOLC || isSpace(c[i])) {
    while (c[i] === EOLC || isSpace(c[i])) i++;
    const open = c[i];
    if (open === 34 || open === 39 || open === 40) {
      const close = open === 40 ? 41 : open;
      i++;
      for (;;) {
        const d = c[i];
        if (d === close) { i++; break; }
        if (d === undefined) { i = -1; break; }
        i++;
        if (d === 92 && (c[i] === close || c[i] === 92)) i++;
      }
      const end = i < 0 ? -1 : afterLine(c, i);
      if (end >= 0) return end;
    }
  }
  return afterLine(c, afterDestination);
}

/** 段落の中身（行の区切りは EOLC）がリンク参照の定義だけか */
function definitionsOnly(c: number[]): boolean {
  let i = 0;
  for (;;) {
    const j = definitionAt(c, i);
    if (j < 0) return false;
    if (j >= c.length) return true;
    i = j + 1;
    while (isSpace(c[i])) i++;
  }
}

type Current = null | { t: 'content'; codes: number[] } | { t: 'indented' } | { t: 'html'; kind: number } | Fence;

/**
 * 一番外側のコードブロックを順に返す（言語を問わない。閉じの無い物は文書の終わりまで）。
 * micromark の document（入れ物）と flow（中身）の手順を行ごとに写したもの。
 */
export function topLevelFences(text: string): TopFence[] {
  const lines = readLines(text);
  const out: TopFence[] = [];
  const stack: Container[] = [];
  let cur: Current = null;
  let hasFlow = false;

  const finishFence = (f: Fence, closedAt: number | null) => {
    if (!f.top) return;
    const last = closedAt ?? f.lastLine;
    // 閉じが無く、文書の最後の行（改行なし）が中身の無い行なら、その行は中身に入らない（remark と同じ）
    const n = closedAt === null && f.lines.length > 0 && f.lines[f.lines.length - 1] === '' && f.eols[f.eols.length - 1] === ''
      ? f.lines.length - 1 : f.lines.length;
    out.push({
      start: lines[f.startLine].start, end: lines[last].end, next: lines[last].next, closed: closedAt !== null, lang: f.lang,
      code: f.lines.slice(0, n).map((s, k) => (k < n - 1 ? s + f.eols[k] : s)).join(''),
    });
  };
  const closeFlow = () => {
    if (cur && cur.t === 'fence') finishFence(cur, null);
    cur = null;
    hasFlow = false;
  };
  const openContainers = (L: MdLine, p: number, interrupt: boolean): number => {
    for (;;) {
      const r = containerAt(L, p, interrupt);
      if (!r) return p;
      stack.push(r[1]);
      p = r[0];
    }
  };

  // 段落の途中の行を切れる物。'setext' は下線、'html7' は遅延継続の行の種類7
  const interrupts = (L: MdLine, q: number, lazy: boolean): null | 'setext' | 'html7' | 'other' => {
    const c = L.codes[q];
    if (c === 35) return atxAt(L, q) ? 'other' : null;
    if (c === 42 || c === 95) return thematicBreakAt(L, q) ? 'other' : null;
    if (c === 45) return !lazy && setextAt(L, q) ? 'setext' : thematicBreakAt(L, q) ? 'other' : null;
    if (c === 61) return !lazy && setextAt(L, q) ? 'setext' : null;
    if (c === 60) { const k = htmlAt(L, q, true, lazy); return k === 7 ? 'html7' : k ? 'other' : null; }
    if (c === 96 || c === 126) return fenceAt(L, q, 0, -1) ? 'other' : null;
    return null;
  };

  // 何も続いていない行の始まり（flow の initial）
  const fresh = (li: number, L: MdLine, p: number, lazy: boolean, afterParagraph: boolean) => {
    if (blankFrom(L, p)) { cur = null; return; }
    // 字下げコード。遅延継続の行で始まった物はその行で終わる（micromark は続きの確かめを、その行の改行の位置で
    // 「この行は遅延継続か」と見るため）
    if (isSpace(L.codes[p]) && spaces(L, p, 4) >= 4) { cur = lazy ? null : { t: 'indented' }; return; }
    const pre = spaces(L, p);
    const q = p + pre;
    const c = L.codes[q];
    if (c === 35 && atxAt(L, q)) { cur = null; return; }
    if ((c === 42 || c === 95) && thematicBreakAt(L, q)) { cur = null; return; }
    if (c === 45 && ((afterParagraph && !lazy && setextAt(L, q)) || thematicBreakAt(L, q))) { cur = null; return; }
    if (c === 61 && afterParagraph && !lazy && setextAt(L, q)) { cur = null; return; }
    if (c === 60) {
      const kind = htmlAt(L, q, false, lazy);
      if (kind) { cur = kind <= 5 && HTML_END[kind].test(slice(L, q)) ? null : { t: 'html', kind }; return; }
    }
    if (c === 96 || c === 126) {
      const f = fenceAt(L, q, pre, li);
      if (f) { cur = f; return; }
    }
    cur = { t: 'content', codes: L.codes.slice(q) };
  };

  // 1行を中身（flow）に渡す。遅延継続の行で、前からの物がこの行をまたいで続くなら true（入れ物を閉じない）
  const feed = (li: number, L: MdLine, p: number, lazy: boolean): boolean => {
    let afterParagraph = false;
    const now = cur;
    if (now) {
      if (now.t === 'content') {
        if (blankFrom(L, p)) cur = null;
        else {
          const pre = spaces(L, p);
          const r = pre >= 4 ? null : interrupts(L, p + pre, lazy);
          if (!r) {
            now.codes.push(EOLC);
            for (let k = p; k < L.codes.length; k++) now.codes.push(L.codes[k]);
            return true;
          }
          cur = null;
          // 遅延継続の行の種類7: micromark はこの HTML の終わりまで見てから段落を閉じるので、この行では
          // 段落が続いている扱いになり、入れ物は閉じない（この HTML は入れ物の中に入る）
          if (r === 'html7') { cur = { t: 'html', kind: 7 }; return true; }
          // Setext の下線は、段落がリンク参照の定義だけなら見出しにならない（その行は新しい段落）
          afterParagraph = r === 'setext' && !definitionsOnly(now.codes);
        }
      } else if (now.t === 'indented') {
        if (!lazy && (blankFrom(L, p) || spaces(L, p, 4) >= 4)) return false;
        cur = null;
      } else if (now.t === 'fence') {
        if (lazy) { finishFence(now, null); cur = null; }
        else if (closesFence(L, p, now)) { finishFence(now, li); cur = null; return false; }
        else {
          const q = now.prefix > 0 ? p + spaces(L, p, now.prefix) : p;
          now.lines.push(slice(L, q)); now.eols.push(L.eol); now.lastLine = li;
          return false;
        }
      } else if ((now.kind === 6 || now.kind === 7) && blankFrom(L, p)) cur = null;
      else if (lazy) cur = null;
      else {
        if (now.kind <= 5 && HTML_END[now.kind].test(slice(L, p))) cur = null;
        return false;
      }
    }
    fresh(li, L, p, lazy, afterParagraph);
    return false;
  };

  const flowLine = (li: number, L: MdLine, p: number, lazy: boolean, continued: number) => {
    hasFlow = true;
    const keep = feed(li, L, p, lazy);
    if (lazy && !keep) stack.length = continued;
    const now = cur as Current;
    if (now && now.t === 'fence' && now.startLine === li) now.top = stack.length === 0;
  };

  for (let li = 0; li < lines.length; li++) {
    const L = lines[li];
    let p = 0;
    let continued = 0;
    while (continued < stack.length) {
      const c = stack[continued];
      const q = c.kind === 'quote' ? quoteAt(L, p) : listContinue(c, L, p);
      if (q < 0) break;
      p = q;
      continued++;
      if (c.kind === 'list' && c.closeFlow) {   // 同じ箇条書きの次の項目: 前の項目の中身を閉じ、内側の入れ物も閉じる
        c.closeFlow = false;
        closeFlow();
        stack.length = continued;
        break;
      }
    }
    let interrupt = false;
    if (continued === stack.length) {
      if (!hasFlow) { flowLine(li, L, openContainers(L, p, false), false, continued); continue; }
      const now = cur as Current;
      if (now && (now.t === 'fence' || now.t === 'html')) { flowLine(li, L, p, false, continued); continue; }
      interrupt = now !== null;
    }
    if (containerAt(L, p, interrupt)) {
      closeFlow();
      stack.length = continued;
      flowLine(li, L, openContainers(L, p, interrupt), false, stack.length);
    } else {
      flowLine(li, L, p, continued !== stack.length, continued);
    }
  }
  closeFlow();
  return out;
}

/**
 * 部品のコードブロック（一番外側の openui-lang / openui）。保存済みの返事は閉じまである物だけ
 * （閉じの無い物は壊れた書き方なので文章のまま）。生成の途中（streaming）なら閉じの無い最後の物も返す。
 */
export function shapeFences(text: string, opts: { streaming?: boolean } = {}): TopFence[] {
  if (!text || (text.indexOf('```') < 0 && text.indexOf('~~~') < 0)) return [];
  return topLevelFences(text).filter((f) => isShapeLang(f.lang) && (f.closed || !!opts.streaming));
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
 * 返事の本文の中の部品のコードブロックを読める文章に置き換える（部品を描けない画面用）。
 * ブロックの見つけ方は shapeFences（split.ts と同じ）。一番外側でない物・HTML ブロックの中は触らない。
 * 読めないブロックはそのまま残す。前後の文章はそのまま（ブロックの後ろの改行は \n にそろう）。
 */
export function replaceShapeBlocks(text: string): string {
  const fences = shapeFences(text);
  if (fences.length === 0) return text;
  let out = '';
  let prev = 0;
  for (const f of fences) {
    const plain = shapeToPlainMarkdown(f.code);
    if (plain === null) continue;
    out += text.slice(prev, f.start) + plain + (f.next > f.end ? '\n' : '');
    prev = f.next;
  }
  return out + text.slice(prev);
}
