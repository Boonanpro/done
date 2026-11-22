'use client';

import { useMemo, useState } from 'react';
import { BookOpen, ChevronRight, FileText, Search } from 'lucide-react';
import { type PromptSummary } from '@/lib/prompts-api';
import { cn } from '@/lib/utils';

export function SkillLibrary({ pages, selected, loaded, onPick }: {
  pages: PromptSummary[]; selected: string; loaded: boolean; onPick: (id: string) => void;
}) {
  const [query, setQuery] = useState('');
  const groups = useMemo(() => {
    const groups = new Map<string, PromptSummary[]>();
    for (const page of pages) {
      const key = page.id.split('/')[1];
      const group = groups.get(key) ?? [];
      group.push(page);
      groups.set(key, group);
    }
    return Array.from(groups).flatMap(([key, group]) => {
      const manual = group.find(p => p.id === 'skill/' + key);
      if (!manual) return [];
      return [{ key, manual, refs: group.filter(p => p !== manual) }];
    });
  }, [pages]);
  const term = query.trim().toLocaleLowerCase();
  const matches = (p: PromptSummary) => (p.title + ' ' + p.id).toLocaleLowerCase().includes(term);
  const shown = groups.filter(g => matches(g.manual) || g.refs.some(matches));

  function pageButton(page: PromptSummary, title: string, path?: string) {
    return (
      <button type="button" key={page.id} onClick={() => onPick(page.id)} aria-pressed={selected === page.id}
        className={cn('flex w-full items-start gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-amber-50', selected === page.id && 'bg-amber-100')}>
        <FileText className="mt-0.5 size-4 shrink-0 text-stone-400" />
        <span className="min-w-0 break-words">{title}{path && <span className="block break-all text-xs text-stone-500">{path}</span>}</span>
      </button>
    );
  }

  return (
    <section aria-label="スキル一覧" className="space-y-3">
      <h2 className="text-lg font-bold">スキル一覧 <span className="text-sm font-normal text-stone-500">{loaded && groups.length + '件'}</span></h2>
      <label className="flex items-center gap-2 rounded-lg border border-stone-300 bg-white px-3">
        <Search className="size-4 shrink-0 text-stone-500" />
        <input type="search" aria-label="スキル・参考ページを検索" placeholder="スキル・参考ページを検索"
          value={query} onChange={e => setQuery(e.target.value)} className="min-w-0 flex-1 bg-transparent py-2 text-sm outline-none" />
      </label>
      {!loaded && <p className="text-sm text-stone-500">読み込み中…</p>}
      {loaded && !shown.length && <p className="text-sm text-stone-600">{term ? '見つかりませんでした。' : '表示できるスキルがありません。'}</p>}
      <div className="grid items-start gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 230px), 1fr))' }}>
      {shown.map(({ key, manual, refs }) => (
        <details key={key} open={Boolean(term) || selected === manual.id || selected.startsWith(manual.id + '/')}
          className="group rounded-lg border border-stone-200 bg-white">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 [&::-webkit-details-marker]:hidden">
            <BookOpen className="size-4 shrink-0 text-amber-700" />
            <span className="min-w-0 flex-1 text-sm font-semibold">{manual.title}{manual.title !== key && <span className="block break-all text-xs font-normal text-stone-500">{key}</span>}</span>
            <ChevronRight className="size-4 shrink-0 text-stone-400 group-open:rotate-90" />
          </summary>
          <div className="space-y-0.5 border-t border-stone-100 p-1">
            {pageButton(manual, '手順書')}
            {(matches(manual) ? refs : refs.filter(matches)).map(p => pageButton(p, p.title, p.id.substring(manual.id.length + 1) + '.md'))}
          </div>
        </details>
      ))}
      </div>
    </section>
  );
}
