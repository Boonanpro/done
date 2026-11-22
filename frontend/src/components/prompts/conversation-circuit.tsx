'use client';

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Activity, AudioLines, BookOpen, CircleStop, Play, Radio } from 'lucide-react';
import { ApiError } from '@/lib/api-client';
import { promptRequest, promptsChat } from '@/lib/prompts-api';
import { architectureTrace, type Trace } from './architecture-trace';
import { NODES } from './architecture';
import { silentTrial, localStep, type CircuitStep } from '@/components/prompts/circuit-audio';

type Room = {id:string; title:string; editor:boolean};
type Item = {origin?:string; id:string; title:string; at:string; state:string; kind:string};
type History = {items:Item[]; selected:string; steps:CircuitStep[]};
const empty: History = {items:[], selected:'', steps:[]};
const nodes: Record<string, string> = Object.fromEntries(NODES.map(n => [n.id, n.name]));
nodes.tool = '道具';
nodes.error = 'エラー';
type CircuitProps = {
  renderDiagram: (trace?: Trace) => ReactNode;
  onPrompt: (id: string, source: string) => void;
};
const field = 'w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900';
const button = 'rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm font-semibold hover:bg-stone-100 disabled:opacity-40';
const format = (date: string) => new Date(date).toLocaleString('ja-JP', {month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit'});
const seconds = (ms:number) => (Math.max(0, ms) / 1000).toFixed(1) + '秒';
const reason = (error: unknown) => error instanceof ApiError ? String((error.data as {detail?:string})?.detail || '記録を取得できませんでした。')
  : error instanceof Error ? error.message : '記録を取得できませんでした。';
const templates = ['この字幕をもう少し大きくして', '明日の予定を教えて', '今どこまで進んでる？'];
function PathView({ steps, title, replaying = false, renderDiagram, onPrompt }: CircuitProps & { steps: CircuitStep[]; title: string; replaying?: boolean }) {
  const [picked, pick] = useState<number | null>(null);
  const index = Math.min(picked ?? steps.length - 1, steps.length - 1);
  const step = steps[index];
  const trace = useMemo(() => architectureTrace(steps, index), [steps, index]);
  const diagram = useRef<HTMLDivElement>(null);
  const [follow, setFollow] = useState(replaying);
  useEffect(() => {
    if (follow && trace.current) {
      diagram.current?.querySelector('[data-trace-state="current"]')?.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
    }
  }, [follow, trace.current]);
  const refs = [...new Set([...(step?.prompts || []), ...(step?.prompt ? [step.prompt] : [])])];
  return <section aria-label={title} className="space-y-2">
    <div className="space-y-2 rounded-xl border border-stone-200 bg-white p-3 text-sm">
      {step ? <>
        <label className="flex items-center gap-2">
          <span className="shrink-0 font-semibold">{title}</span>
          <select aria-label="時刻順の記録" value={index} className={field + ' min-w-0'} onChange={e => pick(Number(e.target.value))}>
            {steps.map((s, i) => <option key={i} value={i}>{i + 1}. {nodes[s.node] || s.node} · {s.label}（+{seconds(Date.parse(s.at) - Date.parse(steps[0].at))}）</option>)}
          </select>
        </label>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <button className={button} disabled={index < 1} onClick={() => pick(index - 1)}>前の段階</button>
          <button className={button} disabled={index >= steps.length - 1} onClick={() => pick(index + 1)}>次の段階</button>

          {picked !== null && <button className="underline" onClick={() => pick(null)}>最新の段階を表示</button>}
          <span className="text-stone-600">{new Date(step.at).toLocaleTimeString('ja-JP')}{step.ms != null && ' · 処理 ' + seconds(step.ms)} {step.model}</span>
        </div>
        {step.detail && <p className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words">{step.detail}</p>}
        {refs.map(id => <button key={id} className="mr-3 inline-flex items-center gap-1 text-xs text-emerald-800 underline" onClick={() => onPrompt(id, step.node)}><BookOpen size={13}/>{id}</button>)}
        <p className="text-xs text-stone-600">緑の箱に記録の順番を表示します。緑の破線は、構成図にある経路のうち途中の時刻が記録されていない区間です。</p>
      </> : <p className="text-stone-500">{title}はまだありません。</p>}
    </div>
    {step && <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-emerald-200 bg-white px-3 py-2 text-sm shadow-sm">
      <span className="min-w-0 font-semibold text-emerald-900">{index + 1}. {nodes[step.node] || step.node} · {step.label}</span>
      <label className="flex shrink-0 items-center gap-1.5"><input type="checkbox" checked={follow} onChange={e => setFollow(e.target.checked)} />図の箱を追う</label>
    </div>}
    <div ref={diagram}>{renderDiagram(trace)}</div>
  </section>;
}

export function ConversationCircuit(props: CircuitProps) {
  const [trialView, setTrialView] = useState<'current' | 'previous' | 'actual'>('current');
  const [rooms,setRooms]=useState<Room[]>([]), [room,setRoom]=useState('');
  const [section,setSection]=useState<'history'|'trial'>('history'), [kind,setKind]=useState('');
  const [selected,select]=useState(''), [history,saveHistory]=useState<History>(empty);
  const [channel,setChannel]=useState<'chat'|'editor'|'voice'>('chat'), [execute,setExecute]=useState(false);
  const [input,setInput]=useState(''), [file,setFile]=useState<File|null>(null);
  const [steps,setSteps]=useState<CircuitStep[]>([]), [baseline,setBaseline]=useState<CircuitStep[]>([]);
  const [busy,setBusy]=useState(false), [error,setError]=useState(''), [historyError,setHistoryError]=useState('');
  const [origin,setOrigin]=useState('');
  const [replay,setReplay]=useState<number|null>(null);
  const controller=useRef<AbortController|null>(null);
  const actionLock=useRef(false);
  const available=rooms.filter(r=>section==='history' || channel==='voice' || r.editor===(channel==='editor'));
  const roomTitle=rooms.find(r=>r.id===room)?.title || '';
  useEffect(()=>{
    let active=true;
    promptRequest<Room[]>('/circuit/rooms').then(rows=>{if(active){
      const q=new URLSearchParams(window.location.search);
      const requested=rows.find(r=>r.id===q.get('room'));
      setRooms(rows);setRoom(requested?.id || rows[0]?.id || '');
      if(requested)select(q.get('selected') || '');
    }}).catch(e=>{if(active)setError(reason(e));});
    return ()=>{active=false;controller.current?.abort();};
  },[]);
  useEffect(()=>{
    if(!room || (section!=='history' && !(execute && channel==='voice' && selected.startsWith('voice/'))))return;
    let active=true, timer:ReturnType<typeof setTimeout>;
    const refresh=async()=>{
      try{
        if(document.visibilityState!=='hidden'){
          const q=new URLSearchParams({room,selected});
          const got=await promptRequest<History>('/circuit/history?'+q);
          if(active){
            const accepted=origin && got.items.find(i=>i.origin===origin);
            if(accepted){select(accepted.id);setOrigin('');}
            saveHistory(got);setHistoryError('');
          }
        }
      }catch(e){if(active)setHistoryError(reason(e));}
      finally{if(active)timer=setTimeout(refresh,3000);}
    };
    void refresh();
    return ()=>{active=false;clearTimeout(timer);};
  },[room,selected,section,origin,execute,channel]);
  useEffect(()=>{
    if(replay===null || replay>=history.steps.length)return;
    const t=setTimeout(()=>setReplay(n=>n===null?null:n+1),650);
    return ()=>clearTimeout(t);
  },[replay,history.steps.length]);
  function changeRoom(id:string){
    setTrialView('current');setRoom(id);setKind('');setOrigin('');select('');saveHistory(empty);setSteps([]);setBaseline([]);setReplay(null);setExecute(false);setError('');setHistoryError('');
  }
  function chooseChannel(next:typeof channel){
    setTrialView('current');setChannel(next);setExecute(false);setFile(null);setSteps([]);setBaseline([]);setError('');
    const nextRooms=rooms.filter(r=>next==='voice'||r.editor===(next==='editor'));
    if(!nextRooms.some(r=>r.id===room))changeRoom(nextRooms[0]?.id || '');
  }
  function mode(next:typeof section){
    setSection(next);setError('');setReplay(null);setExecute(false);
    if(next==='trial' && channel!=='voice' && !rooms.some(r=>r.id===room && r.editor===(channel==='editor'))) {
      changeRoom(rooms.find(r=>r.editor===(channel==='editor'))?.id || '');
    }
  }
  async function run(){
    if(actionLock.current || !room || (!input.trim()&&!file))return;
    if(execute&&!window.confirm('「'+roomTitle+'」で次の依頼を実行しますか？\n\n'+(file?.name||input)))return;
    actionLock.current=true;setBusy(true);setError('');
    const ac=new AbortController();controller.current=ac;
    setTrialView('current');
    if(steps.length)setBaseline(steps);
    setSteps([]);select('');saveHistory(empty);
    const append=(...rows:CircuitStep[])=>{if(!ac.signal.aborted)setSteps(prev=>[...prev,...rows]);};
    try{
      if(channel==='voice'){
        await silentTrial({room,preview:!execute,words:input,file,signal:ac.signal,append,
          session:id=>{select('voice/'+id);}});
      }else if(execute){
        const messageId=crypto.randomUUID();
        await promptsChat.send(input,room,messageId);
        setOrigin(messageId);
        append(localStep('chat','部屋に届いた依頼',input));
        select('');setKind('チャット');setSection('history');
      }else{
        append(...await promptRequest<CircuitStep[]>('/circuit/preview',{room,channel:'chat',words:input}));
      }
    }catch(e){setError(reason(e));}
    finally{actionLock.current=false;setBusy(false);controller.current=null;}
  }
  const items=history.items.filter(i=>!kind||i.kind===kind);
  const shown=selected||history.selected;
  return <div className="min-w-0 space-y-3">
      <nav className="flex gap-1 border-b border-stone-300">{([['history','実際の会話',Radio],['trial','依頼を試す',Activity]] as const).map(([id,title,Icon])=>
        <button key={id} disabled={busy} onClick={()=>mode(id)} aria-pressed={section===id} className={'flex items-center gap-2 border-b-2 px-4 py-2 font-semibold '+(section===id?'border-emerald-800 text-emerald-900':'border-transparent text-stone-500')}><Icon size={16}/>{title}</button>)}</nav>
      {section==='trial' && <div className="flex flex-wrap gap-2">{([['chat','チャット'],['editor','エディターの会話'],['voice','音声（無音）']] as const).map(([id,title])=><button key={id} aria-pressed={channel===id} disabled={busy} onClick={()=>chooseChannel(id)} className={button+' '+(channel===id?'ring-2 ring-emerald-700':'')}>{title}</button>)}</div>}
      <label className="block space-y-1 text-sm font-semibold">会話の部屋<select disabled={busy} className={field} value={room} onChange={e=>changeRoom(e.target.value)}>
        {!available.length&&<option value="">部屋がありません</option>}{available.map(r=><option key={r.id} value={r.id}>{r.title}</option>)}</select></label>
      {error && <p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-900">{error}</p>}
      {section==='history'?<>
        {origin && <p className="text-sm">依頼が届きました。受付の記録を待っています。</p>}
        {historyError && <p role="alert" className="text-sm text-rose-800">{historyError}</p>}
        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-1 text-sm">種類<select className={field} value={kind} onChange={e=>{const k=e.target.value;setKind(k);setReplay(null);select(history.items.find(i=>!k||k===i.kind)?.id||'');}}>
            {['','チャット','音声','並行作業'].map(k=><option key={k} value={k}>{k||'すべて'}</option>)}</select></label>
          <label className="min-w-0 flex-1 space-y-1 text-sm">会話・作業<select className={field} value={shown} onChange={e=>{select(e.target.value);setReplay(null);}}>
            {items.map(i=><option key={i.id} value={i.id}>{format(i.at)} · {i.kind} · {i.title}（{i.state}）</option>)}</select></label>
          <button className={button} disabled={!items.length} onClick={()=>{select('');setKind('');setReplay(null);}}>最新を追う</button>
        </div>
        {items.length>0 && <div className="flex items-center gap-3 text-sm"><span className="inline-flex items-center gap-1 text-emerald-800"><Radio size={15}/>自動更新</span>
        <button className={button} onClick={()=>{if(replay!==null){setReplay(null);}else{select(history.selected);setReplay(1);}}}>{replay===null?'流れを再生':'全体を表示'}</button></div>}
        <PathView {...props} replaying={replay !== null} key={history.selected + (replay === null ? 'watch' : 'replay')} steps={!origin&&shown===history.selected&&items.some(i=>i.id===history.selected)?history.steps.slice(0,replay??undefined):[]} title="記録された流れ"/>
      </>:<>
        <div className="space-y-3 rounded-xl border border-stone-200 bg-white p-4">
          <label className="block space-y-1 text-sm font-semibold">依頼の内容<textarea className={field} rows={3} value={input} maxLength={channel==='voice'?800:8000} disabled={busy||!!file} onChange={e=>setInput(e.target.value)}/></label>
          <div className="flex flex-wrap gap-2">{templates.map(t=><button disabled={busy||!!file} key={t} className="rounded-full border px-3 py-1 text-xs hover:bg-stone-100" onClick={()=>setInput(t)}>{t}</button>)}</div>
          {channel==='voice'&&<label className="block space-y-1 text-sm"><span className="flex items-center gap-1"><AudioLines size={15}/>入力文の読み上げ、または音声ファイル（90秒まで）</span><input type="file" accept="audio/*" disabled={busy} onChange={e=>setFile(e.target.files?.[0]||null)}/></label>}
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={execute} disabled={busy} onChange={e=>setExecute(e.target.checked)}/>この部屋で実際の作業まで進める</label>
          <div className="flex flex-wrap items-center gap-3"><button className="inline-flex items-center gap-2 rounded-lg bg-emerald-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" disabled={busy||!room||(!file&&!input.trim())} onClick={()=>void run()}><Play size={15}/>{execute?'実際に依頼する':'渡す直前まで試す'}</button>
          {busy&&<span className="text-sm">実行中…</span>}{busy&&channel==='voice'&&<button className={button} onClick={()=>controller.current?.abort()}><CircleStop size={16}/>音声テストを終了</button>}</div>
        </div>
        {(baseline.length > 0 || (execute && history.steps.length > 0)) && <div className="flex gap-2">
          {(['current','previous','actual'] as const).filter(v => v === 'current' || (v === 'previous' ? baseline.length > 0 : execute && history.steps.length > 0)).map(v =>
            <button key={v} aria-pressed={trialView === v} className={button + (trialView === v ? ' ring-2 ring-emerald-700' : '')} onClick={() => setTrialView(v)}>{{current:'今回',previous:'前回',actual:'実際の作業'}[v]}</button>)}
        </div>}
        {baseline.length > 0 && steps.length > 0 && <details>
          <summary className="cursor-pointer text-sm">前回と今回の記録を比べる</summary>
          <div className="grid gap-3 py-2 sm:grid-cols-2">
            {[baseline, steps].map((rows, i) => <div key={i} className="min-w-0 rounded-lg border bg-white p-3 text-sm">
              <h3 className="font-semibold">{i === 0 ? '前回' : '今回'}</h3>
              <ol className="mt-2 max-h-80 space-y-2 overflow-auto">{rows.map((s, n) => <li key={n}>
                <strong>{n+1}. {nodes[s.node] || s.node} · {s.label}</strong>
                {s.detail && <p className="whitespace-pre-wrap break-words">{s.detail}</p>}
              </li>)}</ol>
            </div>)}
          </div>
        </details>}
        <PathView {...props} key={trialView} steps={trialView === 'previous' ? baseline : trialView === 'actual' ? history.steps : steps} title={{current:'今回の流れ', previous:'前回の流れ', actual:'実際の作業の流れ'}[trialView]}/>
        {selected.startsWith('voice/')&&!busy&&<button className={button} onClick={()=>{setKind('音声');setSection('history');}}>この音声から始まった作業を見る</button>}
      </>}
  </div>;
}
