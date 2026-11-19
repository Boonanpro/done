// 台本を聞く画面の本文を、Google ドキュメントのように1枚で直せる面にするための部品（2026-11-19）。
// 本文の中身は React に描かせず、ここで作った HTML を1回だけ入れる。打った後の形は、ここで「段落ごとの文字と太字」に
// 読み戻し、前の形と比べて変わった段落だけをドキュメントに書く（app/services/script_listen.py の replace）。
// 文や段落ごとの枠は付けない（11/19 本人「黄色い枠…広範囲に選択できない。余計なものを付けるな」）。
import type { ListenUnit, Seg } from '@/lib/script-listen-api';

/** One paragraph as the screen shows it: its text, boldness per character ('0'/'1') and its paragraph in the doc. */
export type Line = { t: string; b: string; para?: number };
export type Pos = { line: number; off: number };

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const SUG_INS = 'cursor-pointer bg-emerald-50 text-emerald-800 underline decoration-emerald-500 decoration-2 underline-offset-2';
const SUG_DEL = 'cursor-pointer text-red-700/70 line-through decoration-red-500';

function segsHtml(segs: Seg[] | undefined, text: string) {
  if (!segs?.length) return esc(text);
  return segs.map(s => {
    let h = esc(s.t);
    if (s.b) h = `<b>${h}</b>`;
    if (s.blue) h = `<span class="text-sky-700/80">${h}</span>`;
    // Suggestions are decided with 承認 / 却下, not typed over (the doc does not let them be edited either).
    if (s.ins) h = `<span contenteditable="false" data-sug="${esc(s.ins)}" class="${SUG_INS}">${h}</span>`;
    else if (s.del) h = `<span contenteditable="false" data-sug="${esc(s.del)}" class="${SUG_DEL}">${h}</span>`;
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
      out.push(`<div data-skip contenteditable="false" class="my-2"><img src="${esc(u.src)}" alt="サムネ" referrerpolicy="no-referrer" class="w-full max-w-md rounded-md border border-stone-200"></div>`);
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
  let line: (Line & { tt: string[]; bb: string[] }) | null = null;
  const open = (para?: number) => { line = { t: '', b: '', tt: [], bb: [], para }; lines.push(line); return line; };
  const walk = (node: Node, para?: number) => {
    for (const ch of Array.from(node.childNodes)) {
      if (ch.nodeType === 3) {
        const l = line || open(para);
        const bold = markBold(ch.parentElement, root) ? '1' : '0';
        for (const c of (ch as Text).data) { l.tt.push(c === ' ' ? ' ' : c); l.bb.push(bold); }
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
    const x = l as Line & { tt: string[]; bb: string[] };
    return { t: x.tt.join(''), b: x.bb.join(''), para: x.para };
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
    if (t.parentElement?.closest('[contenteditable="false"]')) { left -= t.data.length; last = null; continue; }
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

export type Change = { para_from: number; para_to: number; old: string; new: string; old_bmask: string; new_bmask: string; next: Line[] };

/**
 * What changed between ``base`` (the doc as last written, with its paragraph numbers) and ``now`` (the screen), as
 * whole paragraphs: ``para_from``..``para_to`` read ``old`` and now read ``new`` ('\n' between paragraphs). ``next`` is
 * the new base with the paragraph numbers after the change moved. Null when nothing changed; 'gap' when the change
 * spans something that is not a paragraph (a table) and cannot be written as one piece.
 */
export function diffLines(base: Line[], now: Line[]): Change | null | 'gap' {
  const O = base.map(l => l.t).join('\n'); const OB = base.map(l => l.b).join('0');
  const N = now.map(l => l.t).join('\n'); const NB = now.map(l => l.b).join('0');
  let p = 0;
  while (p < O.length && p < N.length && O[p] === N[p] && OB[p] === NB[p]) p++;
  if (p === O.length && p === N.length) return null;
  let s = 0;
  while (s < O.length - p && s < N.length - p && O[O.length - 1 - s] === N[N.length - 1 - s] && OB[O.length - 1 - s] === NB[N.length - 1 - s]) s++;
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
  const pf = base[lineFrom].para, pt = base[lineTo].para;
  if (pf == null || pt == null || pt - pf !== lineTo - lineFrom) return 'gap';
  for (let k = lineFrom; k <= lineTo; k++) if (base[k].para !== pf + (k - lineFrom)) return 'gap';
  const parts = nt.split('\n');
  let off = 0;
  const made: Line[] = parts.map((t, k) => { const l = { t, b: nb.slice(off, off + t.length), para: pf + k }; off += t.length + 1; return l; });
  const delta = parts.length - (lineTo - lineFrom + 1);
  const next = [
    ...base.slice(0, lineFrom),
    ...made,
    ...base.slice(lineTo + 1).map(l => ({ ...l, para: l.para == null ? l.para : l.para + delta })),
  ];
  return { para_from: pf, para_to: pt, old: O.slice(a, b), new: nt, old_bmask: OB.slice(a, b), new_bmask: nb, next };
}
