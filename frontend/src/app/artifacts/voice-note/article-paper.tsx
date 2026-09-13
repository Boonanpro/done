'use client';
import {useMemo,useRef,useState} from 'react';
import ReactMarkdown from 'react-markdown';
import {GripVertical,LockKeyhole,Trash2} from 'lucide-react';
import styles from './style.module.css';

type Node={type:string;children?:Node[];position?:{start:{offset?:number}};data?:{hName?:string;hProperties?:Record<string,unknown>}};
export function ArticlePaper({free,paid,price,disabled,onMove,onDelete}:{free:string;paid:string;price:number;disabled:boolean;onMove:(free:string,paid:string)=>void;onDelete:(src:string)=>void}){
 const source=free+(free&&paid&&!/\n\s*$/.test(free)?'\n\n':'')+paid;
 const root=useRef<HTMLDivElement>(null);const dragging=useRef(false);const target=useRef<number|null>(null);
 const [guide,setGuide]=useState<number|null>(null);
 function blocks(){return Array.from(root.current?.querySelectorAll<HTMLElement>(':scope > [data-offset]')||[]);}
 function finish(cancel=false){dragging.current=false;setGuide(null);if(!cancel&&target.current!==null)onMove(source.slice(0,target.current),source.slice(target.current));target.current=null;}
 function positions(){return blocks().filter(e=>Number(e.dataset.offset)>0);}
 function marker(){return <div className={styles.dragLine} data-paid-line>
  <button type="button" disabled={disabled} aria-label="有料ラインを移動" title="ドラッグで移動 · ↑↓でも移動" className={styles.lineHandle}
   onPointerDown={e=>{if(disabled)return;e.preventDefault();dragging.current=true;target.current=null;e.currentTarget.setPointerCapture(e.pointerId);}}
   onPointerMove={e=>{if(!dragging.current)return;const choices=positions();if(!choices.length)return;const nearest=choices.reduce((a,b)=>Math.abs(a.getBoundingClientRect().top-e.clientY)<Math.abs(b.getBoundingClientRect().top-e.clientY)?a:b);target.current=Number(nearest.dataset.offset);setGuide(nearest.getBoundingClientRect().top-root.current!.getBoundingClientRect().top);let scroller:HTMLElement|null=root.current;while(scroller&&scroller.scrollHeight<=scroller.clientHeight+1)scroller=scroller.parentElement;if(scroller){const rect=scroller.getBoundingClientRect();if(e.clientY<Math.max(0,rect.top)+70)scroller.scrollTop-=24;if(e.clientY>Math.min(window.innerHeight,rect.bottom)-70)scroller.scrollTop+=24;}}}
   onPointerUp={()=>finish()} onPointerCancel={()=>finish(true)}
   onKeyDown={e=>{if(e.key==='Escape'){finish(true);return;}if(e.key!=='ArrowUp'&&e.key!=='ArrowDown')return;e.preventDefault();const offsets=positions().map(n=>Number(n.dataset.offset));const next=e.key==='ArrowUp'?offsets.filter(n=>n<free.length).at(-1):offsets.find(n=>n>free.length);if(next!==undefined)onMove(source.slice(0,next),source.slice(next));}}>
   <GripVertical size={18}/><LockKeyhole size={13}/><span>{price>0?`有料 · ¥${price.toLocaleString()}`:'有料ライン'}</span>
  </button>
 </div>;}
 const annotate=()=> (tree:Node)=>{const children=tree.children||[];let placed=false;const result:Node[]=[];for(const child of children){const offset=child.position?.start.offset;if(offset!==undefined){if(!placed&&offset>=free.length){result.push({type:'paragraph',children:[],data:{hName:'div',hProperties:{'data-marker':true}}});placed=true;}child.data={...child.data,hProperties:{...child.data?.hProperties,'data-offset':offset}};}result.push(child);}if(!placed)result.push({type:'paragraph',children:[],data:{hName:'div',hProperties:{'data-marker':true}}});tree.children=result;};
 const components=useMemo(()=>({div:()=>marker(),img:({src,alt}:{src?:string|Blob;alt?:string})=><span className={styles.mediaFrame}><img src={src} alt={alt||''}/>{alt&&<small>{alt}</small>}{typeof src==='string'&&<button type="button" className={styles.mediaDelete} disabled={disabled} aria-label="画像を削除" title="画像を削除" onClick={()=>onDelete(src)}><Trash2 size={17}/></button>}</span>}),[source,free.length,price,disabled,onMove,onDelete]);
 return <div ref={root} className={`${styles.paper} ${styles.draggablePaper}`}>
 <ReactMarkdown remarkPlugins={[annotate]} components={components}>{source}</ReactMarkdown>
 {guide!==null&&<div className={styles.dropGuide} style={{top:guide}}/>}
 </div>;
}
