'use client';

import { useEffect, useRef, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { ADOBE_FONT_CSS, ADOBE_FONTS } from './adobe-fonts';
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
  const [loaded, setLoaded] = useState(false);
  const [font, setFont] = useState('');
  const [confirming, setConfirming] = useState<Item>();
  const [removing, setRemoving] = useState(false);
  const [active, setActive] = useState('');
  const [chosen, setChosen] = useState<Item>();
  const [values, setValues] = useState<Values>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    dialog.current?.showModal();
    const controller = new AbortController();
    fetch('/api/envato-shelf', { signal: controller.signal })
      .then(async r => { if (!r.ok) throw Error(); setItems(await r.json()); setLoaded(true); })
      .catch(() => { if (!controller.signal.aborted) setError('一覧を読み込めませんでした。'); });
    return () => controller.abort();
  }, []);
  function choose(item: Item) {
    setValues(Object.fromEntries(item.fields.map(f => [f.label, f.type === 'photos' ? [] : ''])));
    setFont('');
    setChosen(item);
  }
  async function remove(item: Item) {
    if (removing) return;
    setRemoving(true);
    setError('');
    try {
      const response = await fetch(`/api/envato-shelf?id=${encodeURIComponent(item.id)}`, { method: 'DELETE' });
      if (!response.ok) throw Error();
      const remaining = items.filter(i => i.id !== item.id);
      setItems(remaining);
      if (!remaining.some(i => i.group === group)) setGroup('すべて');
      setConfirming(undefined);
    } catch {
      setError('削除できませんでした。もう一度お試しください。');
    } finally {
      setRemoving(false);
    }
  }
  const photos = assets.filter(a => a.kind === 'image');
  return <dialog ref={dialog} onCancel={close} aria-label="Envatoの部品" className="m-auto w-[min(1120px,96vw)] max-w-none rounded-xl border border-border bg-background p-0 text-foreground shadow-2xl backdrop:bg-black/65">
    <style>{ADOBE_FONT_CSS}</style>
    <div className="flex max-h-[88dvh] flex-col">
      <header className="flex items-center justify-between border-b px-5 py-3">
        <h2 className="font-semibold">{chosen ? chosen.name : 'Envatoの部品'}</h2>
        <button type="button" onClick={close} aria-label="閉じる" className="px-2 text-xl">×</button>
      </header>
      {error && <p role="alert" className="px-5 py-2 text-sm text-destructive">{error}</p>}
      {confirming ? <div className="space-y-4 p-5">
        <p>「{confirming.name}」を部品の棚から削除しますか？</p>
        <div className="flex gap-3">
          <button type="button" autoFocus disabled={removing} onClick={() => setConfirming(undefined)}>キャンセル</button>
          <button type="button" disabled={removing} onClick={() => remove(confirming)} className="rounded bg-destructive px-3 py-2 text-white">棚から削除する</button>
        </div>
      </div> : chosen ? <form className="grid gap-5 overflow-auto p-5 md:grid-cols-2" onSubmit={async e => {
        e.preventDefault(); if (busy) return;
        setBusy(true);
        try {
          const note = `Envatoの部品「${chosen.name}」（${chosen.id}）を、この指示の開始時刻に配置。作品ごとのEnvato登録を確認してplace_envato_componentを使う。${font ? `書体（font）は ${font} を指定。` : ''}差し替え欄（写真は素材ID） ${JSON.stringify(values)}`;
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
          {chosen.fields.some(f => f.type === 'text') && <fieldset>
            <legend className="mb-2 text-sm font-semibold">書体</legend>
            <div className="grid grid-cols-2 gap-2">
              <label className="col-span-2 flex items-center gap-2 text-sm"><input type="radio" name="font" checked={!font} onChange={() => setFont('')}/>部品の標準書体</label>
              {Object.values(ADOBE_FONTS).map(f => <label key={f.face} className={`cursor-pointer rounded border p-2 ${font === f.face ? 'border-primary' : ''}`}>
                <span className="flex items-center gap-2 text-xs"><input type="radio" name="font" value={f.face} aria-label={f.label} checked={font === f.face} onChange={() => setFont(f.face)}/>{f.label}</span>
                <span aria-hidden="true" className="mt-1 block break-words text-xl" style={{fontFamily: f.face, fontWeight: f.weight}}>
                  {String(values[chosen.fields.find(x => x.type === 'text')!.label] || '映像と言葉')}</span>
              </label>)}
            </div>
          </fieldset>}
          {!photos.length && chosen.fields.some(f=>f.type.startsWith('photo')) && <p className="text-sm">作品に使う写真を素材に追加してください。</p>}
          <div className="flex gap-3"><button type="button" onClick={()=>setChosen(undefined)}>一覧に戻る</button>
            <button disabled={busy} className="rounded bg-primary px-3 py-2 text-primary-foreground">{busy?'依頼中…':'この位置に入れる'}</button></div>
        </div>
      </form> : <>
        <div className="flex flex-wrap gap-2 px-5 py-3">{['すべて', ...new Set(items.map(i=>i.group))].map(g=><button type="button" key={g} aria-pressed={g===group} onClick={()=>setGroup(g)} className={`rounded-full px-3 py-1 text-sm ${g===group?'bg-foreground text-background':'bg-muted'}`}>{g}</button>)}</div>
        <div className="overflow-auto px-5 pb-5">
          {!items.length && !error && <p>{loaded ? '棚に部品がありません。' : '読み込み中…'}</p>}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{items.filter(i=>group==='すべて'||i.group===group).map(i=><div key={i.id} className="relative rounded-lg border hover:border-primary">
            <button type="button" onClick={()=>choose(i)} onPointerEnter={()=>setActive(i.id)} onPointerLeave={()=>setActive('')} onFocus={()=>setActive(i.id)} onBlur={()=>setActive('')}
            className="w-full overflow-hidden rounded-lg text-left"><img alt="" className="aspect-video w-full object-cover" src={active===i.id?i.motion:i.still}/>
            <div className="flex items-center justify-between gap-1 p-2 text-sm"><span>{i.name}</span><span className="shrink-0 text-xs text-muted-foreground">{i.duration}秒</span></div></button>
            <button type="button" aria-label={`${i.name}を棚から削除`} title="棚から削除"
              onClick={() => {setError(''); setConfirming(i);}}
              className="absolute right-1.5 top-1.5 grid h-8 w-8 place-items-center rounded-md bg-black/70 text-white hover:bg-red-700 focus-visible:bg-red-700"><Trash2 size={16}/></button>
          </div>)}</div>
        </div>
      </>}
    </div>
  </dialog>;
}
