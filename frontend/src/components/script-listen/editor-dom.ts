// 台本を聞く画面の本文を、Google ドキュメントのように1枚で直せる面にするための部品（2026-11-19）。
// 本文の中身は React に描かせず、ここで作った HTML を1回だけ入れる。打った後の形は、ここで「段落ごとの文字と太字」に
// 読み戻し、前の形と比べて変わった段落だけをドキュメントに書く（app/services/script_listen.py の replace）。
// 文や段落ごとの枠は付けない（11/19 本人「黄色い枠…広範囲に選択できない。余計なものを付けるな」）。
import type { ListenUnit, Seg } from '@/lib/script-listen-api';

/** One paragraph as the screen shows it: its text, boldness per character ('0'/'1'), which characters were struck
 * here in suggestion mode and not yet sent ('1', the doc still has them plain) and its paragraph in the doc. */
export type Line = { t: string; b: string; d: string; para?: number };
export type Pos = { line: number; off: number };

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const SUG_INS = 'bg-emerald-50 text-emerald-800 underline decoration-emerald-500 decoration-2 underline-offset-2';
const SUG_DEL = 'text-red-700/70 line-through decoration-red-500';
// The owner's own suggestions (suggestion mode on this screen) in their own colour, the way Docs colours each writer.
export const OWN_INS = 'bg-violet-50 text-violet-800 underline decoration-violet-500 decoration-2 underline-offset-2';
export const OWN_DEL = 'text-violet-700/70 line-through decoration-violet-500';
export const isOwnSuggestion = (id?: string | null) => !!id && id.startsWith('o-');

function segsHtml(segs: Seg[] | undefined, text: string) {
  if (!segs?.length) return esc(text);
  return segs.map(s => {
    let h = esc(s.t);
    if (s.b) h = `<b>${h}</b>`;
    if (s.blue) h = `<span class="text-sky-700/80">${h}</span>`;
    // Suggestions can be typed in like any text (11/20 本人「提案モードの文字…普通に編集できるようにしてほしい」): the
    // server settles a suggestion whose words are changed (script_listen_marks).
    // Dan's words inside the owner's suggestion (they wrote over his) stay in his colour; only what they typed is
    // theirs (11/21 本人「書き換えた部分全部が紫になる…全部はおかしい」).
    const own = (id: string) => isOwnSuggestion(id) && s.who !== 'dan';
    const who = s.who === 'dan' ? ' data-who="dan"' : '';
    if (s.ins) h = `<span data-sug="${esc(s.ins)}" data-kind="ins"${who} class="${own(s.ins) ? OWN_INS : SUG_INS}">${h}</span>`;
    else if (s.del) h = `<span data-sug="${esc(s.del)}" data-kind="del"${who} class="${own(s.del) ? OWN_DEL : SUG_DEL}">${h}</span>`;
    return h;
  }).join('');
}

const P_CLASS = {
  title: 'mb-3 text-[20px] font-bold leading-snug',
  topHead: 'mt-3 text-[14px] font-bold text-stone-700',
  scriptHead: 'mb-2 mt-8 text-[15px] font-bold text-stone-500',
  topNote: 'my-1 text-[14px] leading-relaxed text-stone-700',
  h2: 'mb-2 mt-8 border-b border-stone-300 pb-1 text-[17px] font-bold text-stone-800',
  h3: 'mb-1 mt-5 text-[15px] font-semibold text-amber-800',
  note: 'my-2 text-[14px] leading-relaxed text-sky-700/80',
  body: 'my-2.5 text-[16.5px] leading-[1.95]',
} as const;

/** The whole doc as one editable piece of HTML, paragraph by paragraph in the doc's order. */
export function buildHtml(units: ListenUnit[]) {
  let inScript = !units.some(u => u.kind === 'heading' && u.level === 1 && u.text.startsWith('◎台本'));
  const out: string[] = [];
  let box = false;
  const region = (top: boolean) => {
    if (top && !box) { out.push('<div data-box class="mb-6 rounded-lg border border-stone-200 bg-white/80 px-4 py-3">'); box = true; }
    if (!top && box) { out.push('</div>'); box = false; }
  };
  let i = 0;
  while (i < units.length) {
    const u = units[i];
    if (u.kind === 'image') {
      region(!inScript);
      // A picture of Dan's suggestion is framed in the suggestion's colour and opens its card; one of the doc's own
      // can be taken out here (11/20 本人「この読み上げページ（台本エディター）には画像も貼れるようにしたい」).
      const sug = u.ins || u.del;
      const frame = u.ins ? 'border-2 border-emerald-500' : u.del ? 'border-2 border-red-400 opacity-50' : 'border border-stone-200';
      const tag = sug
        ? `<span class="pointer-events-none mb-0.5 block text-[11px] font-semibold ${u.ins ? 'text-emerald-700' : 'text-red-600'}">${u.ins ? '提案で入る画像' : '提案で消える画像'}</span>`
        : u.id ? `<button type="button" data-img-del="${esc(u.id)}" aria-label="画像を消す" title="画像をドキュメントから消す" class="absolute right-1.5 top-1.5 hidden rounded bg-stone-900/70 px-1.5 py-0.5 text-[11px] text-white group-hover:block">消す</button>` : '';
      const w = inScript ? 'max-w-xl' : 'max-w-md';
      // A thumbnail of the top part opens the thumbnail editor (parts, pen, finish) right here (11/20 本人「ダンと一緒に
      // サムネ編集して仕上げたりしたい…この読み上げ画面の中で」).
      const thumb = !inScript && !sug && u.thumb_order != null
        ? `<button type="button" data-thumb-edit="${u.thumb_order}" data-thumb-object="${esc(u.id || '')}" class="absolute bottom-2 right-2 flex items-center gap-1 rounded-full bg-stone-900/80 px-2.5 py-1 text-[12px] font-semibold text-white shadow active:bg-stone-900">✎ サムネを直す</button>` : '';
      out.push(`<div data-skip data-img="${esc(u.id || '')}"${u.para != null ? ` data-img-para="${u.para}"` : ''} contenteditable="false"${sug ? ` data-sug="${esc(sug)}"` : ''} class="group relative my-2 w-fit ${w}">${sug ? tag : ''}<img src="${esc(u.src)}" alt="${inScript ? '画像' : 'サムネ'}" referrerpolicy="no-referrer" draggable="false" class="block w-full rounded-md ${frame}${thumb ? ' cursor-pointer' : ''}"${thumb ? ` data-thumb-img="${u.thumb_order}"` : ''}>${sug ? '' : tag}${thumb}</div>`);
      i++; continue;
    }
    const para = (u as { para?: number }).para;
    if (para == null) { i++; continue; }
    const group: ListenUnit[] = [u];
    while (i + group.length < units.length && (units[i + group.length] as { para?: number }).para === para) group.push(units[i + group.length]);
    i += group.length;
    if (u.kind === 'heading' && u.level === 1) inScript = u.text.startsWith('◎台本');
    const top = u.kind !== 'title' && !inScript;
    region(top);
    let cls: string = P_CLASS.body;
    if (u.kind === 'title') cls = P_CLASS.title;
    else if (u.kind === 'heading') cls = u.level === 1 ? (top ? P_CLASS.topHead : P_CLASS.scriptHead) : u.level === 2 ? P_CLASS.h2 : P_CLASS.h3;
    else if (top) cls = P_CLASS.topNote;
    else if (group.every(g => g.kind === 'note')) cls = P_CLASS.note;
    if (group.length === 1 && u.kind !== 'say') {
      const segs = 'segs' in u ? u.segs : undefined;
      const inner = segsHtml(segs, u.text);
      out.push(`<p id="u-${u.n}" data-n="${u.n}" data-para="${para}" class="${cls}">${inner || '<br>'}</p>`);
      continue;
    }
    const inner = group.map(g => {
      const segs = 'segs' in g ? g.segs : undefined;
      return `<span id="u-${g.n}" data-n="${g.n}">${segsHtml(segs, 'text' in g ? g.text : '')}</span>`;
    }).join('');
    out.push(`<p data-para="${para}" class="${cls}">${inner || '<br>'}</p>`);
  }
  region(false);
  return out.join('');
}

const BLOCK = /^(P|DIV|H[1-6]|LI|UL|OL|BLOCKQUOTE|SECTION|PRE)$/;
const isBlock = (n: Node): n is HTMLElement => n.nodeType === 1 && BLOCK.test((n as Element).tagName);
const skipped = (n: Node) => n.nodeType === 1 && (n as HTMLElement).hasAttribute('data-skip');
const hasBlockInside = (el: Element) => !!el.querySelector('p,div,h1,h2,h3,h4,h5,h6,li,ul,ol,blockquote,section,pre');

/** Bold as a mark (<b>, <strong>, an inline font-weight), the nearest one winning; a heading's own bold does not count. */
function markBold(el: Element | null, root: Element) {
  for (let e = el; e && e !== root; e = e.parentElement) {
    if (e.tagName === 'B' || e.tagName === 'STRONG') return true;
    const w = (e as HTMLElement).style?.fontWeight;
    if (w) return w === 'bold' || w === 'bolder' || Number(w) >= 600;
  }
  return false;
}

/** The surface read back as paragraphs (a <p> or <div> per paragraph, a <br> in the middle of one splits it). */
export function extract(root: HTMLElement): Line[] {
  const lines: Line[] = [];
  let line: (Line & { tt: string[]; bb: string[]; dd: string[] }) | null = null;
  const open = (para?: number) => { line = { t: '', b: '', d: '', tt: [], bb: [], dd: [], para }; lines.push(line); return line; };
  const walk = (node: Node, para?: number) => {
    for (const ch of Array.from(node.childNodes)) {
      if (ch.nodeType === 3) {
        const l = line || open(para);
        const bold = markBold(ch.parentElement, root) ? '1' : '0';
        const struck = ch.parentElement?.closest('[data-od]') ? '1' : '0';
        // U+200B: the place Japanese input starts in, in suggestion mode (listen-screen readyCompose); not a letter.
        for (const c of (ch as Text).data) { if (c === '\u200b') continue; l.tt.push(c === ' ' ? ' ' : c); l.bb.push(bold); l.dd.push(struck); }
      } else if (ch.nodeType === 1) {
        const el = ch as HTMLElement;
        if (skipped(el)) continue;
        if (el.tagName === 'BR') {
          if (line) line = null;
          else if (el.nextSibling) { open(para); line = null; }
          continue;
        }
        if (isBlock(el)) {
          line = null;
          const p = el.dataset.para != null ? Number(el.dataset.para) : undefined;
          if (!hasBlockInside(el)) open(p);
          walk(el, p);
          line = null;
        } else {
          walk(el, para);
        }
      }
    }
  };
  walk(root);
  return lines.map(l => {
    const x = l as Line & { tt: string[]; bb: string[]; dd: string[] };
    return { t: x.tt.join(''), b: x.bb.join(''), d: x.dd.join(''), para: x.para };
  });
}

/** The paragraph elements in order (the same order as extract's lines when there are no <br> splits). */
export function leaves(root: HTMLElement) {
  return Array.from(root.querySelectorAll<HTMLElement>('p,div,h1,h2,h3,h4,h5,h6,li,blockquote,pre'))
    .filter(el => !el.closest('[data-skip]') && !hasBlockInside(el));
}

/** Where the caret is: which paragraph and how many characters into it. */
export function getPos(root: HTMLElement, node?: Node | null, offset?: number): Pos | null {
  const sel = window.getSelection();
  const n = node ?? sel?.focusNode ?? null;
  const o = offset ?? sel?.focusOffset ?? 0;
  if (!n || !root.contains(n)) return null;
  const list = leaves(root);
  const el = n.nodeType === 1 ? (n as Element) : n.parentElement;
  const leaf = list.find(l => l === el || l.contains(n));
  if (!leaf) return null;
  const r = document.createRange();
  r.setStart(leaf, 0);
  try { r.setEnd(n, o); } catch { return { line: list.indexOf(leaf), off: 0 }; }
  return { line: list.indexOf(leaf), off: r.toString().length };
}

/** The text node and offset at a Pos. */
export function nodeAt(root: HTMLElement, pos: Pos): { node: Node; off: number } | null {
  const leaf = leaves(root)[pos.line];
  if (!leaf) return null;
  const w = document.createTreeWalker(leaf, NodeFilter.SHOW_TEXT);
  let left = pos.off;
  let last: Text | null = null;
  for (let t = w.nextNode() as Text | null; t; t = w.nextNode() as Text | null) {
    if (left <= t.data.length) return { node: t, off: Math.max(0, left) };
    left -= t.data.length;
    last = t;
  }
  return last ? { node: last, off: last.data.length } : { node: leaf, off: 0 };
}

export function setPos(root: HTMLElement, pos: Pos) {
  const at = nodeAt(root, pos);
  if (!at) return;
  const sel = window.getSelection();
  const r = document.createRange();
  r.setStart(at.node, at.off);
  r.collapse(true);
  sel?.removeAllRanges();
  sel?.addRange(r);
}

export type Change = {
  para_from: number; para_to: number; old: string; new: string; old_bmask: string; new_bmask: string; new_dmask: string; next: Line[];
};

/**
 * What changed between ``base`` (the doc as last written, with its paragraph numbers) and ``now`` (the screen), as
 * whole paragraphs: ``para_from``..``para_to`` read ``old`` and now read ``new`` ('\n' between paragraphs). ``next`` is
 * the new base with the paragraph numbers after the change moved. Null when nothing changed; 'gap' when the change
 * spans something that is not a paragraph (a table) and cannot be written as one piece.
 */
export function diffLines(base: Line[], now: Line[]): Change | null | 'gap' {
  const dm = (l: Line) => l.d || '0'.repeat(l.t.length);
  const O = base.map(l => l.t).join('\n'); const OB = base.map(l => l.b).join('0'); const OD = base.map(dm).join('0');
  const N = now.map(l => l.t).join('\n'); const NB = now.map(l => l.b).join('0'); const ND = now.map(dm).join('0');
  const same = (i: number, j: number) => O[i] === N[j] && OB[i] === NB[j] && OD[i] === ND[j];
  let p = 0;
  while (p < O.length && p < N.length && same(p, p)) p++;
  if (p === O.length && p === N.length) return null;
  let s = 0;
  while (s < O.length - p && s < N.length - p && same(O.length - 1 - s, N.length - 1 - s)) s++;
  const oldEnd = O.length - s;
  const count = (str: string, upto: number) => { let c = 0; for (let k = 0; k < upto; k++) if (str[k] === '\n') c++; return c; };
  const lineFrom = count(O, p);
  const lineTo = count(O, Math.max(p, oldEnd));
  const starts: number[] = [];
  let acc = 0;
  for (const l of base) { starts.push(acc); acc += l.t.length + 1; }
  const a = starts[lineFrom];
  const b = starts[lineTo] + base[lineTo].t.length;
  const tail = O.length - b;
  const nt = N.slice(a, N.length - tail);
  const nb = NB.slice(a, NB.length - tail);
  const nd = ND.slice(a, ND.length - tail);
  const pf = base[lineFrom].para, pt = base[lineTo].para;
  if (pf == null || pt == null || pt - pf !== lineTo - lineFrom) return 'gap';
  for (let k = lineFrom; k <= lineTo; k++) if (base[k].para !== pf + (k - lineFrom)) return 'gap';
  const parts = nt.split('\n');
  let off = 0;
  const made: Line[] = parts.map((t, k) => {
    const l = { t, b: nb.slice(off, off + t.length), d: nd.slice(off, off + t.length), para: pf + k };
    off += t.length + 1;
    return l;
  });
  const delta = parts.length - (lineTo - lineFrom + 1);
  const next = [
    ...base.slice(0, lineFrom),
    ...made,
    ...base.slice(lineTo + 1).map(l => ({ ...l, para: l.para == null ? l.para : l.para + delta })),
  ];
  return { para_from: pf, para_to: pt, old: O.slice(a, b), new: nt, old_bmask: OB.slice(a, b), new_bmask: nb, new_dmask: nd, next };
}
