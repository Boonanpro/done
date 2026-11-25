'use client';

import { useEffect, useRef, useState } from 'react';
import type { SequenceAsset } from './video-review-editor';

type Field = {label: string; type: 'text' | 'number' | 'photos' | 'photo'; example: string | number | string[]};
type Item = {id: string; name: string; group: string; sourceName: string; url: string; duration: number;
  still: string; motion: string; fields: Field[]};
type Values = Record<string, string | string[] | number>;

export function EnvatoShelf({assets, close, submit}: {
  assets: SequenceAsset[]; close: () => void; submit: (note: string, name: string) => Promise<boolean>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [error, setError] = useState('');
  const [group, setGroup] = useState('すべて');
  const [active, setActive] = useState('');
  const [chosen, setChosen] = useState<Item>();
  const [values, setValues] = useState<Values>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    dialog.current?.showModal();
    const controller = new AbortController();
    fetch('/api/envato-shelf', { signal: controller.signal })
      .then(async r => { if (!r.ok) throw Error(); setItems(await r.json()); })
      .catch(() => { if (!controller.signal.aborted) setError('一覧を読み込めませんでした。'); });
    return () => controller.abort();
  }, []);
  function choose(item: Item) {
    setValues(Object.fromEntries(item.fields.map(f => [f.label, f.type === 'photos' ? [] : ''])));
    setChosen(item);
  }
  const photos = assets.filter(a => a.kind === 'image');
  return <dialog ref={dialog} onCancel={close} aria-label="Envatoの部品" className="m-auto w-[min(1120px,96vw)] max-w-none rounded-xl border border-border bg-background p-0 text-foreground shadow-2xl backdrop:bg-black/65">
    <div className="flex max-h-[88dvh] flex-col">
      <header className="flex items-center justify-between border-b px-5 py-3">
        <h2 className="font-semibold">{chosen ? chosen.name : 'Envatoの部品'}</h2>
        <button type="button" onClick={close} aria-label="閉じる" className="px-2 text-xl">×</button>
      </header>
      {chosen ? <form className="grid gap-5 overflow-auto p-5 md:grid-cols-2" onSubmit={async e => {
        e.preventDefault(); if (busy) return;
        setBusy(true);
        try {
          const note = `Envatoの部品「${chosen.name}」（${chosen.id}）を、この指示の開始時刻に配置。作品ごとのEnvato登録を確認してplace_envato_componentを使う。差し替え欄（写真は素材ID） ${JSON.stringify(values)}`;
          if (await submit(note, chosen.name)) close();
        } finally { setBusy(false); }
      }}>
        <div><img src={chosen.motion} alt={chosen.name} className="w-full rounded bg-neutral-900"/>
          <a href={chosen.url} target="_blank" rel="noreferrer" className="mt-2 block text-xs underline">{chosen.sourceName} · Envato</a></div>
        <div className="flex flex-col gap-3">
          {chosen.fields.map(f => <label key={f.label} className="grid gap-1 text-sm">{f.label}
            {f.type === 'photos' || f.type === 'photo' ? <select multiple={f.type === 'photos'} required className="rounded border bg-background p-2"
              value={values[f.label]} onChange={e => setValues({...values, [f.label]: f.type === 'photos' ? Array.from(e.target.selectedOptions, o=>o.value) : e.target.value})}>
              {f.type === 'photo' && <option value="">写真を選ぶ</option>}
              {photos.map(a=><option key={a.id} value={a.id}>{a.label || a.id}</option>)}
            </select> : <input required type={f.type === 'number' ? 'number' : 'text'} step="any" placeholder={String(f.example)} className="rounded border bg-background p-2" value={values[f.label]} onChange={e=>setValues({...values,[f.label]:e.target.value})}/>}
          </label>)}
          {!photos.length && chosen.fields.some(f=>f.type.startsWith('photo')) && <p className="text-sm">作品に使う写真を素材に追加してください。</p>}
          <div className="flex gap-3"><button type="button" onClick={()=>setChosen(undefined)}>一覧に戻る</button>
            <button disabled={busy} className="rounded bg-primary px-3 py-2 text-primary-foreground">{busy?'依頼中…':'この位置に入れる'}</button></div>
        </div>
      </form> : <>
        <div className="flex flex-wrap gap-2 px-5 py-3">{['すべて', ...new Set(items.map(i=>i.group))].map(g=><button type="button" key={g} aria-pressed={g===group} onClick={()=>setGroup(g)} className={`rounded-full px-3 py-1 text-sm ${g===group?'bg-foreground text-background':'bg-muted'}`}>{g}</button>)}</div>
        <div className="overflow-auto px-5 pb-5">
          {!items.length && <p>{error || '読み込み中…'}</p>}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{items.filter(i=>group==='すべて'||i.group===group).map(i=><button type="button" key={i.id} onClick={()=>choose(i)} onPointerEnter={()=>setActive(i.id)} onPointerLeave={()=>setActive('')} onFocus={()=>setActive(i.id)} onBlur={()=>setActive('')}
            className="overflow-hidden rounded-lg border text-left hover:border-primary"><img alt="" className="aspect-video w-full object-cover" src={active===i.id?i.motion:i.still}/>
            <div className="flex items-center justify-between gap-1 p-2 text-sm"><span>{i.name}</span><span className="shrink-0 text-xs text-muted-foreground">{i.duration}秒</span></div></button>)}</div>
        </div>
      </>}
    </div>
  </dialog>;
}
