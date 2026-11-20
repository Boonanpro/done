'use client';

// 見本の台本を横に並べて比べる欄（2026-11-20 本人「参考にした動画の台本も添えて、横並びにして比較できる比較モード」）。
// 見本の台本は app/services/script_listen_refs.py（~/.dan/script-listen/references/<doc>.json）。
// 見本の段は、台本の見出しと名前で（無ければ順番で）並び、本文で今いる段の見本が光って欄の中で見える所へ来る。
import { useEffect, useMemo, useRef, useState } from 'react';
import { ExternalLink, PlayCircle } from 'lucide-react';

import type { Reference } from '@/lib/script-listen-api';
import { cn } from '@/lib/utils';

export interface SectionHead { n: number; text: string; level: number }

const norm = (s: string) => s.replace(/[▼◎■●・【】［］\[\]「」\s　]/g, '');

function fmt(sec: number) {
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

function at(url: string, sec: number) {
  try {
    const u = new URL(url);
    u.searchParams.set('t', `${sec}s`);
    return u.toString();
  } catch {
    return url;
  }
}

/** Which heading of the script each section of a reference lines up with: the heading of that name, or (renamed
 * or missing) the heading at the same place among the script's top headings (【】, or ▼ when there are no 【】). */
export function lineUp(ref: Reference, heads: SectionHead[]): (number | null)[] {
  const byName = new Map(heads.map(h => [norm(h.text), h.n]));
  const top = Math.min(...heads.map(h => h.level));
  const tops = heads.filter(h => h.level === top);
  return ref.sections.map((s, i) => byName.get(norm(s.match)) ?? tops[i]?.n ?? null);
}

/** The section of the reference for where the owner is: the last one whose heading is at or above that place. */
function sectionAt(lined: (number | null)[], here: number | null): number {
  if (here == null) return -1;
  let best = -1, bestN = -1;
  lined.forEach((n, i) => { if (n != null && n <= here && n > bestN) { best = i; bestN = n; } });
  return best;
}

export function RefsPanel({ refs, heads, here, onGo, side }: {
  refs: Reference[];
  heads: SectionHead[];
  /** The heading the owner is at in the script. */
  here: number | null;
  onGo: (n: number) => void;
  side: boolean;
}) {
  const [pick, setPick] = useState(0);
  const ref = refs[Math.min(pick, refs.length - 1)];
  const boxRef = useRef<HTMLDivElement>(null);
  const lined = useMemo(() => (ref ? lineUp(ref, heads) : []), [ref, heads]);
  const headText = useMemo(() => new Map(heads.map(h => [h.n, h.text])), [heads]);

  // Bring the section that lines up with where the owner is into view (inside this box only, the script does not move).
  useEffect(() => {
    const box = boxRef.current;
    if (!box || here == null) return;
    const i = sectionAt(lined, here);
    const el = i >= 0 ? box.querySelector<HTMLElement>(`[data-ref-sec="${i}"]`) : null;
    if (!el) return;
    const top = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop - 8;
    box.scrollTo({ top, behavior: 'smooth' });
  }, [here, lined, pick]);

  const lit = sectionAt(lined, here);
  if (!ref) return null;
  return (
    <div className={cn('flex min-h-0 min-w-0 flex-1 flex-col bg-white', side ? 'border-l border-stone-200' : 'border-t-2 border-stone-300')}>
      <div className="shrink-0 border-b border-stone-200 px-3 py-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[12px] font-semibold text-stone-500">見本</span>
          {refs.map((r, i) => (
            <button
              key={r.id}
              type="button"
              data-testid="ref-tab"
              onClick={() => setPick(i)}
              className={cn('rounded-full border px-2.5 py-0.5 text-[12px]', i === pick
                ? 'border-sky-700 bg-sky-700 text-white' : 'border-stone-300 bg-white text-stone-700')}
            >
              {r.who}<span className="hidden sm:inline">「{r.title}」</span>
            </button>
          ))}
          {ref.url && (
            <a href={ref.url} target="_blank" rel="noreferrer" className="ml-auto flex items-center gap-1 text-[12px] text-sky-700 underline-offset-2 hover:underline">
              <ExternalLink className="h-3.5 w-3.5" />動画{ref.length && `（${ref.length}）`}
            </a>
          )}
        </div>
        {ref.note && <div className="mt-1 text-[11px] text-stone-500">{ref.note}</div>}
      </div>
      <div ref={boxRef} data-testid="ref-box" className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-24 pt-2">
        {ref.sections.map((s, i) => {
          const n = lined[i];
          const on = i === lit;
          return (
            <section key={i} data-ref-sec={i} className={cn('mb-3 rounded-lg px-2.5 py-2 transition-colors', on ? 'bg-sky-50 ring-1 ring-sky-300' : '')}>
              <div className="mb-1 flex items-center gap-2">
                <button
                  type="button"
                  disabled={n == null}
                  onClick={() => n != null && onGo(n)}
                  title="台本のこの段へ"
                  className="min-w-0 flex-1 truncate text-left text-[13px] font-bold text-stone-700 hover:text-sky-800 disabled:hover:text-stone-700"
                >
                  {(n != null && headText.get(n)) || s.match}
                </button>
                {s.start != null && ref.url && (
                  <a href={at(ref.url, s.start)} target="_blank" rel="noreferrer" className="flex shrink-0 items-center gap-0.5 text-[12px] tabular-nums text-sky-700">
                    <PlayCircle className="h-3.5 w-3.5" />{fmt(s.start)}
                  </a>
                )}
              </div>
              {s.text
                ? s.text.split('\n').map((p, j) => <p key={j} className="mb-1.5 text-[14px] leading-relaxed text-stone-800">{p}</p>)
                : <p className="text-[13px] text-stone-400">この動画には、この段に当たる所がありません。</p>}
            </section>
          );
        })}
      </div>
    </div>
  );
}
