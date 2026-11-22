import { useId } from 'react';
import type { CircuitStep } from './circuit-audio';

const positions: [string, string, number, number][] = [
  ['owner','みきさん',70,106], ['voice','音声のダン',233,48], ['chat','チャットのダン',233,162],
  ['router','振り分け',400,48], ['editor','エディター',400,162],
  ['parallel','作業担当',567,162], ['lookup','調査',567,48], ['backend','通話の担当',400,265],
  ['stage','通話の画面',73,265], ['tool','道具',567,265], ['error','エラー',233,265],
];
export function CircuitMap({steps, index, pick}:{steps:CircuitStep[]; index:number; pick:(i:number)=>void}) {
  const marker = useId().replace(/:/g,'');
  const observed = steps.slice(0,index+1);
  const last = new Map<string,number>();
  const edges = new Map<string,{from:string; to:string; order:number}>();
  observed.forEach((s,i)=>{
    last.set(s.node,i);
    if(i && observed[i-1].node!==s.node){
      const from=observed[i-1].node;
      edges.set(from+'/'+s.node,{from,to:s.node,order:i});
    }
  });
  // Keep alternative destinations visible; light only recorded transitions.
  const xy = new Map(positions.map(([key,,x,y])=>[key,{x,y}]));
  return <div className="overflow-x-auto rounded-xl border border-stone-300 bg-[#f0f4ee]">
    <svg className="mx-auto block min-w-[510px] w-full max-w-[820px]" viewBox="0 0 640 312" role="group" aria-label="会話が通った順に光る回路図">
      <defs><pattern id={marker+'grid'} width="14" height="14" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".85" fill="#c4cec2"/></pattern>
        <marker id={marker} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0 L9 5 L0 10z" fill="#178064"/></marker></defs>
      <rect width="640" height="312" fill={'url(#'+marker+'grid)'}/>
      {[...edges.values()].map(({from,to,order})=>{
        const a=xy.get(from),b=xy.get(to);if(!a||!b)return null;
        const down=b.y>a.y;const side=b.x>=a.x?1:-1;
        const routeY=a.y===b.y?a.y-34:(a.y+b.y)/2+(side>0?-7:7);
        const ax=a.x+(a.y===b.y?side*14:0),bx=b.x+(a.y===b.y?-side*14:0);
        const ay=a.y+(a.y===b.y?-19:(down?19:-19)),by=b.y+(a.y===b.y?-23:(down?-23:23));
        return <path key={from+to} d={`M${ax},${ay} V${routeY} H${bx} V${by}`} fill="none" stroke={order===index?'#096747':'#649582'} strokeWidth={order===index?3.5:2} markerEnd={'url(#'+marker+')'}/>;
      })}
      {positions.map(([id,title,x,y])=>{
        const i=last.get(id), active=id===steps[index]?.node;
        const select=()=>{if(i!==undefined)pick(i);};
        return <g key={id} role="button" aria-label={title+(i===undefined?'（記録なし）':'の記録')} aria-disabled={i===undefined}
          tabIndex={i===undefined?-1:0} onClick={select} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}}}
          style={{cursor:i===undefined?'default':'pointer'}} transform={`translate(${x} ${y})`}>
          <rect x="-64" y="-19" width="128" height="38" rx="8" fill={active?'#10553f':i===undefined?'#f3f5f1':'white'} stroke={i===undefined?'#d4dcd3':'#3d8067'} strokeWidth={active?2.5:1.4}/>
          <circle cx="-53" cy="0" r="3.2" fill={active?'#7ef2a9':i===undefined?'#ced6ca':'#26875d'}/>
          <text textAnchor="middle" dominantBaseline="central" x="3" fontSize="13" fontWeight={active?700:500} fill={active?'white':i===undefined?'#6a776b':'#1b493a'}>{title}</text>
        </g>;
      })}
    </svg>
  </div>;
}
