'use client';

import {useRef,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {ChevronLeft,ChevronRight,RefreshCw,X} from 'lucide-react';

export type GalleryItem={url:string;kind:'image'|'video';name?:string};
export function mediaKind(url:string):GalleryItem['kind']|null {
 const path=url.split(/[?#]/)[0];
 if(/\.(mp4|mov|m4v|webm|avi|mkv)$/i.test(path))return 'video';
 if(/\.(png|jpe?g|gif|webp|avif|heic|bmp)$/i.test(path))return 'image';
 return null;
}
export function collectChatMedia(source:Element|null, fallback:GalleryItem[]=[]):GalleryItem[]{
 const scope=source?.closest('[data-media-gallery-scope]');
 const items:GalleryItem[]=[];
 scope?.querySelectorAll('[data-media-items]').forEach(node=>{
  try{const values=JSON.parse(node.getAttribute('data-media-items')||'[]');if(Array.isArray(values))for(const item of values){if(typeof item.url==='string'&&(item.kind==='image'||item.kind==='video'))items.push(item)}}catch{/* Ignore incomplete streamed markup. */}
 });
 return [...items,...fallback].filter((item,i,all)=>all.findIndex(x=>x.url===item.url)===i);
}
export function MediaViewer({items,initialUrl,onClose,returnFocus}:{items:GalleryItem[];initialUrl:string;onClose:()=>void;returnFocus?:HTMLElement|null}){
 const [index,setIndex]=useState(()=>Math.max(0,items.findIndex(x=>x.url===initialUrl)));
 const [retry,setRetry]=useState(0),[failed,setFailed]=useState(false);
 const gesture=useRef<{x:number;y:number}|null>(null);
 const en=typeof document!=='undefined'&&document.documentElement.lang.startsWith('en');
 const label=(english:string,japanese:string)=>en?english:japanese;
 const item=items[index];
 const go=(next:number)=>{if(next<0||next>=items.length)return;setFailed(false);setRetry(0);setIndex(next)};
 if(!item)return null;
 const control='flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20 focus-visible:outline-2 focus-visible:outline-white disabled:opacity-25';
 return <Dialog.Root open onOpenChange={open=>{if(!open)onClose()}}><Dialog.Portal>
  <Dialog.Overlay className="fixed inset-0 z-[200] bg-black/95"/>
  <Dialog.Content aria-describedby={undefined} onCloseAutoFocus={e=>{if(returnFocus){e.preventDefault();returnFocus.focus()}}} onKeyDown={e=>{if(e.target instanceof HTMLVideoElement)return;if(e.key==='ArrowLeft'){e.preventDefault();go(index-1)}if(e.key==='ArrowRight'){e.preventDefault();go(index+1)}}} className="fixed inset-0 z-[201] flex flex-col bg-black text-white outline-none" style={{paddingTop:'max(8px, env(safe-area-inset-top))',paddingBottom:'max(8px, env(safe-area-inset-bottom))'}}>
   <Dialog.Title className="sr-only">{label('Chat media','チャットのメディア')}</Dialog.Title>
   <header className="flex shrink-0 items-center justify-between px-4 py-1"><span aria-live="polite" className="text-sm tabular-nums">{index+1} / {items.length}</span><Dialog.Close className={control} aria-label={label('Close media','メディアを閉じる')}><X/></Dialog.Close></header>
   <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden" style={{touchAction:'pan-y pinch-zoom'}} onPointerDown={e=>{if(!e.isPrimary)return;const rect=e.currentTarget.getBoundingClientRect();if(item.kind==='video'&&e.clientY>rect.bottom-80)return;gesture.current={x:e.clientX,y:e.clientY}}} onPointerCancel={()=>{gesture.current=null}} onPointerUp={e=>{const start=gesture.current;gesture.current=null;if(!start)return;const dx=e.clientX-start.x,dy=e.clientY-start.y;if(Math.abs(dx)>55&&Math.abs(dx)>Math.abs(dy)*1.4)go(index+(dx<0?1:-1))}}>
    {item.kind==='video'?<video key={`${item.url}-${retry}`} src={item.url} controls autoPlay playsInline preload="metadata" className="h-full w-full object-contain" onError={()=>setFailed(true)}/>:<img key={`${item.url}-${retry}`} src={item.url} alt={item.name||label('Photo','画像')} draggable={false} className="h-full w-full select-none object-contain" onError={()=>setFailed(true)}/>}
    {failed&&<div role="alert" className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-black"><p>{label('Could not load this media','メディアを読み込めませんでした')}</p><button type="button" className={control} aria-label={label('Retry','再試行')} onClick={()=>{setFailed(false);setRetry(x=>x+1)}}><RefreshCw/></button></div>}
   </div>
   <footer className="flex shrink-0 items-center justify-between gap-4 px-4 py-2"><button type="button" className={control} disabled={index===0} onClick={()=>go(index-1)} aria-label={label('Previous media','前のメディア')}><ChevronLeft/></button><span className="truncate text-sm">{item.name||''}</span><button type="button" className={control} disabled={index===items.length-1} onClick={()=>go(index+1)} aria-label={label('Next media','次のメディア')}><ChevronRight/></button></footer>
  </Dialog.Content>
 </Dialog.Portal></Dialog.Root>;
}
