'use client';

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Pause, Play, SkipBack, SkipForward } from 'lucide-react';
import { NODES } from './architecture';
import { architectureTrace, stepNode, transition, type Trace } from './architecture-trace';
import type { CircuitStep } from './circuit-audio';

export interface MapActions {
  renderDiagram: (trace?: Trace) => ReactNode;
  onPrompt: (id: string, source: string) => void;
  onEdit: (node: string) => void;
}
const names = Object.fromEntries(NODES.map(n => [n.id, n.name]));
const plain: Record<string,string> = {
  '本人から届いた言葉':'みきさんから依頼が届きました。', '本人の言葉':'みきさんがチャットに書きました。',
  'ダンの返事':'ダンがチャットで返事をしました。', 'チャットで受付':'チャットのダンが依頼を受け取りました。',
  '完了':'ダンの作業が終わりました。', '作業終了':'ダンの作業が終わりました。',
  '振り分けに渡す言葉':'依頼の言葉を受け取りました。', 'チャットのダンに渡す直前':'チャットのダンへ渡す文を用意しました。',
  'エディターのダンに渡す直前':'エディターに渡す文を用意しました。', '作業担当に渡す直前':'作業担当に渡す文を用意しました。',
};
function summary(step: CircuitStep) {
  return step.activity || plain[step.label] || step.label;
}
const button = 'inline-flex items-center justify-center gap-1 rounded-md border border-stone-300 bg-white px-2 py-1.5 text-xs font-semibold hover:bg-stone-100 disabled:opacity-40';
const sec = (ms: number) => Number((ms / 1000).toFixed(1)) + '秒';
function gap(steps: CircuitStep[], i: number) {
  return steps[i+1] ? Math.max(0,Date.parse(steps[i+1].at)-Date.parse(steps[i].at)) : 0;
}

export function RequestPlayback({steps, live, renderDiagram, onPrompt, onEdit}: MapActions & {steps: CircuitStep[]; live:boolean}) {
  const last = steps.length-1;
  const [cursor, setCursor] = useState(last);
  const [playing, setPlaying] = useState(false);
  const [following, setFollowing] = useState(live);
  const [speed, setSpeed] = useState(1);
  const [inspected, inspect] = useState('');
  const index = Math.min(Math.max(0,cursor), last);
  const step = steps[index];
  const map = useRef<HTMLDivElement>(null);
  const log = useRef<HTMLOListElement>(null);
  const elapsed = useRef(0);
  const prevLength = useRef(steps.length);
  const current = stepNode(step), next = stepNode(steps[index+1]);
  const trace = useMemo(() => architectureTrace(steps,index),[steps,index]);

  const seek = useCallback((at:number) => {
    elapsed.current = 0;
    setPlaying(false);
    setFollowing(false);
    setCursor(at);
  },[]);
  const inspectBox = (node:string, at:number) => { seek(at); inspect(node); };
  useEffect(() => {
    // The first snapshot immediately shows the selected request's actual state.
    if (!prevLength.current && steps.length) setCursor(last);
    prevLength.current = steps.length;
  },[steps.length,last]);

  // One clock controls the particle AND arrival. A pause keeps its exact position.
  const advancing = playing || (following && index < last);
  useLayoutEffect(() => {
    const dot = map.current?.querySelector<SVGCircleElement>('[data-flow-particle]');
    if (!dot) return;
    dot.setAttribute('visibility','hidden');
    if (index < 0 || index >= last || (!advancing && !elapsed.current)) return;
    const segments = transition(current, next).flatMap(segment => {
      const path = map.current?.querySelector<SVGPathElement>('[data-flow-path="'+segment.key+'"]');
      return path ? [{path, reverse:segment.reverse, length:path.getTotalLength()}] : [];
    });
    const total = segments.reduce((sum,s) => sum+s.length,0);
    function paint(t:number) {
      if (!dot || !total) return;
      let distance = total * Math.max(0, Math.min(1,(t-0.20)/0.80));
      for (const seg of segments) {
        if (distance <= seg.length || seg === segments[segments.length-1]) {
          const pt = seg.path.getPointAtLength(seg.reverse ? seg.length-distance : distance);
          dot.setAttribute('cx',String(pt.x));
          dot.setAttribute('cy',String(pt.y));
          dot.setAttribute('visibility', t >= 0.20 ? 'visible' : 'hidden');
          break;
        }
        distance -= seg.length;
      }
    }
    paint(elapsed.current);
    if (!advancing) return;
    let frame = 0, previous = performance.now();
    const duration = following ? Math.min(750,1800 / Math.max(1,last-index)) : 1600 / speed;
    const tick = (time:number) => {
      elapsed.current = Math.min(1,elapsed.current+(time-previous)/duration);
      previous = time;
      paint(elapsed.current);
      if (elapsed.current < 1) frame = requestAnimationFrame(tick);
      else {
        elapsed.current = 0;
        setCursor(index+1);
        if (index+1 >= last) setPlaying(false);
      }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  },[advancing,current,next,index,last,speed,following]);

  useLayoutEffect(() => {
    const root = map.current;
    const card = root?.querySelector<HTMLElement>('[data-trace-state="current"]');
    if (!root || !card) return;
    const frame = root.getBoundingClientRect(), rect = card.getBoundingClientRect();
    if (rect.top < frame.top+10 || rect.bottom > frame.bottom-10) {
      root.scrollTo({top:root.scrollTop + rect.top - frame.top - frame.height*0.4, behavior:'instant'});
    }
    const pan = card.closest<HTMLElement>('.overflow-x-auto');
    if (pan) {
      const port = pan.getBoundingClientRect();
      if (rect.left < port.left || rect.right > port.right) {
        pan.scrollLeft += rect.left + rect.width/2-port.left-port.width/2;
      }
    }
  },[current]);
  useEffect(() => {
    const list = log.current, row = list?.children[index] as HTMLElement | undefined;
    if (list && row) list.scrollTop += row.getBoundingClientRect().top-list.getBoundingClientRect().top-list.clientHeight/3;
  },[index]);
  if (!step) return <>{renderDiagram()}</>;

  const selectedNode = inspected || current;
  const visits = steps.slice(0,index+1).filter(s=>stepNode(s)===selectedNode);
  const references = [...new Set(visits.flatMap(s=>[...(s.prompts || []), ...(s.prompt ? [s.prompt] : [])]))];
  const messages = [...new Set(visits.map(s=>s.handoff || (/渡す直前|渡った依頼文/.test(s.label) ? s.detail : '')).filter(Boolean))];
  const wait = gap(steps,index);
  function togglePlayback() {
    inspect('');
    setFollowing(false);
    if (playing) { setPlaying(false); return; }
    if (index === last) {elapsed.current = 0; setCursor(0);}
    setPlaying(true);
  }
  return <section aria-label="依頼の流れ" className="@container rounded-xl border border-stone-300 bg-white">
    <div className="grid min-w-0 @min-[790px]:grid-cols-[minmax(0,1fr)_230px]">
      <div ref={map} data-request-map className="min-w-0 overflow-y-auto overscroll-contain" style={{height:'clamp(320px,56vh,640px)'}}>
        {renderDiagram({...trace,activity:summary(step),inspect:inspectBox})}
      </div>
      <aside className="min-w-0 border-t border-stone-200 bg-stone-50 p-3 @min-[790px]:border-l @min-[790px]:border-t-0">
        <h3 className="mb-2 text-sm font-bold">作業の様子</h3>
        <ol aria-label="時間順の作業" ref={log} className="max-h-32 overflow-y-auto overscroll-contain @min-[790px]:max-h-[min(46vh,520px)]">
          {steps.map((s,i)=><li key={s.at+i}><button aria-current={i===index?'step':undefined} onClick={()=>{seek(i);inspect('');}}
            className={'w-full rounded-md border-l-2 px-2 py-1.5 text-left text-xs '+(i===index?'border-emerald-700 bg-emerald-100 text-emerald-950':'border-stone-200 hover:bg-white')}>
            <span className="block text-[10px] text-stone-600">{new Date(s.at).toLocaleTimeString('ja-JP')} · {names[stepNode(s)] || s.label}</span>
            <span className="line-clamp-2">{summary(s)}</span>{gap(steps,i)>=10000 && <span className="block text-amber-800">次の記録まで{sec(gap(steps,i))}</span>}
          </button></li>)}
        </ol>
      </aside>
    </div>
    <div aria-label="再生の操作" className="flex flex-wrap items-center gap-2 border-t bg-stone-50 px-3 py-2">
      <button className={button} aria-label="1段戻る" disabled={!index} onClick={()=>{inspect('');seek(index-1);}}><SkipBack size={15}/></button>
      <button className={button} disabled={!last} onClick={togglePlayback}>{playing?<Pause size={15}/>:<Play size={15}/>} {playing?'一時停止':'流れを再生'}</button>
      <button className={button} aria-label="1段進む" disabled={index===last} onClick={()=>{inspect('');seek(index+1);}}><SkipForward size={15}/></button>
      <input className="min-w-16 flex-1 accent-emerald-700" aria-label="再生位置" type="range" min={0} max={last} value={index} onChange={e=>{inspect('');seek(Number(e.target.value));}}/>
      <span className="text-xs tabular-nums">{index+1} / {steps.length}</span>
      <select className={button} aria-label="再生速度" value={speed} onChange={e=>setSpeed(Number(e.target.value))}>{[0.5,1,2].map(n=><option key={n} value={n}>{n}倍</option>)}</select>
      {live && <button aria-pressed={following} className={button} onClick={()=>{seek(last);inspect('');setFollowing(true);}}>{following?'最新を表示中':'最新に戻る'}</button>}
    </div>
    <div className="space-y-2 border-t p-3 text-sm">
      <p className="font-semibold text-emerald-950">{names[current] || step.label} · {summary(step)}</p>
      {wait>=10000 && <p className="text-xs text-amber-800">次の記録まで{sec(wait)}空いています。</p>}
      <details open={!!inspected || undefined} key={inspected+':'+index}>
        <summary className="cursor-pointer text-xs font-semibold">この段階の記録と指示文</summary>
        <div className="mt-2 space-y-2 rounded-lg bg-stone-50 p-3">
          <p>{step.ms!=null?'処理にかかった時間 '+sec(step.ms):'処理時間の記録なし'}{step.model && ' · '+step.model}</p>
          <p className="font-semibold">ここまでに読んだ指示文とスキル</p>
          {references.length?references.map(id=><button key={id} className="mr-2 text-emerald-800 underline" onClick={()=>onPrompt(id,selectedNode)}>{id}</button>):<p>読み込みの記録なし</p>}
          <p className="font-semibold">担当に渡した文の全文</p>
          {messages.length?messages.map((msg,i)=><p key={i} className="max-h-56 overflow-auto whitespace-pre-wrap break-words">{msg}</p>):<p>引き継いだ文の記録なし</p>}
          {step.detail && !messages.includes(step.detail) && <p className="max-h-56 overflow-auto whitespace-pre-wrap break-words">{step.detail}</p>}
          {selectedNode && <button className={button} onClick={()=>onEdit(selectedNode)}>この箱の指示文を開く</button>}
        </div>
      </details>
    </div>
  </section>;
}
