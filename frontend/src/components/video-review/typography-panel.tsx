'use client';
import { useState } from 'react';

export type EditableTypography = { template: string; values: string[]; starts?: number[]; ends?: number[] };
type Props = { room:string; content:string; clip:string; asset:string; spec:EditableTypography; time:number; onSaved:()=>void | Promise<void> };
export function TypographyPanel({room,content,clip,asset,spec,time,onSaved}: Props) {
  const at = spec.starts?.findLastIndex((s,i) => s <= time && time < (spec.ends?.[i] ?? Infinity)) ?? 0;
  const [index,setIndex] = useState(Math.max(0,at));
  const [values,setValues] = useState([...spec.values]);
  const [busy,setBusy] = useState(false);
  const [status,setStatus] = useState('');
  async function save() {
    setBusy(true);setStatus('元の書体と効果で描画しています…');
    try {
      const r = await fetch('/api/editor-typography',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({room,content,clip,asset,values})});
      if (!r.ok) throw Error(r.status===401 || r.status===403 ? 'ログインを確認してください' : '変更を受け付けられませんでした');
      const {id}=await r.json();
      for (;;) {
        await new Promise(resolve => setTimeout(resolve,2200));
        const response=await fetch('/api/editor-typography?id='+encodeURIComponent(id),{cache:'no-store'});
        if(!response.ok) throw Error('描画結果の取得に失敗しました');
        const result=await response.json();
        if(result.pending) continue;
        if(!result.ok) throw Error(result.error);
        await onSaved();setStatus('反映しました');break;
      }
    } catch(err) {setStatus(err instanceof Error ? err.message : '変更を反映できませんでした');}
    finally {setBusy(false);}
  }
  return <div className="space-y-2 rounded border border-border p-2" data-typography-editor>
    <label className="block text-xs font-medium">文字を編集
      {values.length>1 && <select aria-label="編集するテロップ" className="mt-1 block w-full rounded border bg-background p-1"
        value={index} onChange={e=>setIndex(Number(e.target.value))}>{spec.values.map((v,i)=><option key={i} value={i}>{v}</option>)}</select>}
      <textarea aria-label="テロップの文字" rows={2} className="mt-1 block w-full rounded border bg-background p-2"
        value={values[index]} disabled={busy} maxLength={300}
        onChange={e=>setValues(values.map((v,i)=>i===index ? e.target.value : v))}/>
    </label>
    <button type="button" className="rounded border border-border px-2 py-1 text-xs" onClick={()=>void save()}
      disabled={busy || values.some(v=>!v.trim()) || values.every((v,i)=>v===spec.values[i])}>文字を反映</button>
    {status && <p role="status" className="text-xs">{status}</p>}
  </div>;
}
