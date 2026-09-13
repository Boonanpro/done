'use client';
import {forwardRef,useEffect,useImperativeHandle,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {renderToStaticMarkup} from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import {GripVertical,LockKeyhole,Trash2,Sparkles} from 'lucide-react';
import styles from './style.module.css';
const BOUNDARY='<!--voice-note-paid-->';
function markdown(node:Node):string {
 if(node.nodeType===3)return (node.textContent||'').replace(/\u00a0/g,' ').replace(/\u200b/g,'');
 if(!(node instanceof HTMLElement))return Array.from(node.childNodes).map(markdown).join('');
 if(node.hasAttribute('data-paid-line'))return '\n\n'+BOUNDARY+'\n\n';
 if(node.hasAttribute('data-ui'))return '';
 const text=Array.from(node.childNodes).map(markdown).join('');
 switch(node.tagName){
 case 'BR':return '\n';
 case 'STRONG':case 'B':return '**'+text+'**';
 case 'EM':case 'I':return '*'+text+'*';
 case 'S':case 'DEL':return '~~'+text+'~~';
 case 'H1':case 'H2':case 'H3':case 'H4':return '\n\n'+'#'.repeat(Number(node.tagName[1]))+' '+text.trim()+'\n\n';
 case 'A':return '['+text+']('+node.getAttribute('href')+')';
 case 'IMG':return '!['+(node.getAttribute('alt')||'').replace(/[\[\]]/g,'')+']('+node.getAttribute('src')+')';
 case 'PRE':return '\n\n```\n'+(node.textContent||'').replace(/\n$/,'')+'\n```\n\n';
 case 'CODE':return '`'+text+'`';
 case 'BLOCKQUOTE':return '\n\n'+text.trim().split('\n').map(l=>'> '+l).join('\n')+'\n\n';
 case 'UL':case 'OL':return '\n\n'+Array.from(node.children).map((li,i)=>(node.tagName==='OL'?`${i+1}. `:'- ')+markdown(li).trim().replace(/\n/g,'\n  ')).join('\n')+'\n\n';
 case 'P':case 'DIV':return '\n\n'+text+'\n\n';
 case 'HR':return '\n\n---\n\n';
 default:return text;
 }
}
function clean(text:string){return text.replace(/\n{3,}/g,'\n\n').trim();}
export type PaperHandle={freezeSelection:()=>void;replaceSelection:(text:string)=>boolean;insertImage:(url:string,target?:string)=>void;format:(command:string,value?:string)=>void};
type Props={free:string;paid:string;disabled:boolean;onMove:(free:string,paid:string)=>void;onDelete:(src:string)=>void;onSelection:(text:string)=>void;onImage:(src:string)=>void};
export const InlinePaper=forwardRef<PaperHandle,Props>(function InlinePaper({free,paid,disabled,onMove,onDelete,onSelection,onImage},ref){
 const root=useRef<HTMLDivElement>(null),last=useRef(''),selected=useRef<Range|null>(null),drag=useRef<HTMLElement|null>(null),target=useRef<Element|null>(null),guide=useRef<HTMLDivElement>(null);
 const callbacks=useRef({onMove,onDelete,onSelection,onImage});callbacks.current={onMove,onDelete,onSelection,onImage};
 const [toolbar,setToolbar]=useState<{left:number;top:number}|null>(null);
 const markerHTML=useRef('');const frozen=useRef<Range|null>(null);
 function emit(){if(!root.current)return;if(!root.current.querySelector('[data-paid-line]'))root.current.insertAdjacentHTML('beforeend',markerHTML.current);const text=markdown(root.current);const parts=text.split(BOUNDARY);const next=[clean(parts[0]),clean(parts.slice(1).join(''))];last.current=JSON.stringify(next);callbacks.current.onMove(next[0],next[1]);}
 function capture(){
 const s=window.getSelection(),editor=root.current;
 if(!s?.rangeCount||!editor?.contains(s.anchorNode)||!editor.contains(s.focusNode)){setToolbar(null);return;}
 const range=s.getRangeAt(0);selected.current=range.cloneRange();callbacks.current.onSelection(s.toString());
 if(s.isCollapsed||!s.toString().trim()){setToolbar(null);return;}
 const rects=Array.from(range.getClientRects()).filter(r=>r.width&&r.height&&r.bottom>0&&r.top<innerHeight);
 const rect=rects[0];if(!rect){setToolbar(null);return;}
 const width=Math.min(320,innerWidth-16);
 setToolbar({left:Math.max(8,Math.min(rect.left,innerWidth-width-8)),top:rect.top>=52?rect.top-46:Math.min(innerHeight-48,rect.bottom+6)});
 }
 function format(command:string,value?:string){if(restore()){const range=window.getSelection()?.getRangeAt(0),line=root.current?.querySelector('[data-paid-line]');if(range&&line&&range.intersectsNode(line))return;document.execCommand(command,false,value);emit();capture();}}
 function restore(){if(!selected.current||!root.current?.contains(selected.current.commonAncestorContainer))return false;const s=window.getSelection();s?.removeAllRanges();s?.addRange(selected.current);return true;}
 useImperativeHandle(ref,()=>({
 freezeSelection(){frozen.current=selected.current?.cloneRange()||null;},
 replaceSelection(text){selected.current=frozen.current;if(!restore())return false;const html=renderToStaticMarkup(<ReactMarkdown>{text}</ReactMarkdown>).replace(/^<p>([\s\S]*)<\/p>$/,'$1');document.execCommand('insertHTML',false,html);emit();return true;},
 insertImage(url,imageTarget){if(imageTarget){const image=Array.from(root.current?.querySelectorAll('img')||[]).find(i=>i.getAttribute('src')===imageTarget);if(image){image.setAttribute('src',url);emit();last.current='';return;}}selected.current=frozen.current;if(!restore()){root.current?.focus();const range=document.createRange();range.selectNodeContents(root.current!);range.collapse(false);window.getSelection()?.removeAllRanges();window.getSelection()?.addRange(range);}document.execCommand('insertHTML',false,renderToStaticMarkup(<p><img src={url} alt=""/></p>));emit();last.current='';},
 format
 }));
 useEffect(()=>{const next=JSON.stringify([free,paid]);if(next===last.current)return;last.current=next;selected.current=null;
 const media={img:({src,alt}:{src?:string|Blob;alt?:string})=><span className={styles.mediaFrame} contentEditable={false}><img src={src} alt={alt||''}/><button data-ui data-image-delete type="button" className={styles.mediaDelete} aria-label="画像を削除" title="画像を削除"><Trash2 size={17}/></button><button data-ui data-image-ai type="button" className={`${styles.mediaDelete} ${styles.mediaAI}`} aria-label="画像をAIで編集" title="画像をAIで編集"><Sparkles size={17}/></button></span>};
 const line=<div data-paid-line contentEditable={false} className={styles.dragLine}><button type="button" aria-label="有料ラインを移動" title="ドラッグで移動" className={styles.lineHandle}><GripVertical size={18}/><LockKeyhole size={13}/>ここから先は有料部分です</button></div>;markerHTML.current=renderToStaticMarkup(line);
 if(root.current){
 root.current.innerHTML=renderToStaticMarkup(<><ReactMarkdown components={media}>{free||'\u200b'}</ReactMarkdown>{line}<ReactMarkdown components={media}>{paid||'\u200b'}</ReactMarkdown></>);
 // Legacy image descriptions become ordinary paragraphs on the next edit/save.
 root.current.querySelectorAll('img[alt]').forEach(image=>{
 const caption=image.getAttribute('alt');if(!caption)return;
 const paragraph=document.createElement('p');paragraph.textContent=caption;
 const anchor=image.closest('p')||image.parentElement!;
 anchor.after(paragraph);image.setAttribute('alt','');
 });
 }

 },[free,paid]);
 useEffect(()=>{const fn=()=>capture();document.addEventListener('selectionchange',fn);window.addEventListener('scroll',fn,true);window.addEventListener('resize',fn);return()=>{document.removeEventListener('selectionchange',fn);window.removeEventListener('scroll',fn,true);window.removeEventListener('resize',fn);};},[]);
 // Protect the boundary before the browser mutates the editable DOM (including cut/mobile deletion).
 useEffect(()=>{
 const editor=root.current;if(!editor)return;
 const beforeInput=(event:InputEvent)=>{
  const line=editor.querySelector('[data-paid-line]');const selection=window.getSelection();
  if(!line||!selection?.rangeCount)return;
  const current=selection.getRangeAt(0);
  if(!editor.contains(current.commonAncestorContainer))return;
  const ranges=event.getTargetRanges?.()||[];
  const touches=ranges.some(part=>{const r=document.createRange();r.setStart(part.startContainer,part.startOffset);r.setEnd(part.endContainer,part.endOffset);return r.intersectsNode(line);});
  if(touches||(!current.collapsed&&current.intersectsNode(line))){
   event.preventDefault();
   if(!current.collapsed&&event.inputType.startsWith('delete')){
    // Delete only the selected content on either side. Keep the actual boundary node.
    const left=current.cloneRange(),right=current.cloneRange();
    left.setEndBefore(line);right.setStartAfter(line);
    right.deleteContents();left.deleteContents();
    const cursor=document.createRange();cursor.setStartBefore(line);cursor.collapse(true);
    selection.removeAllRanges();selection.addRange(cursor);emit();capture();
   }
   return;
  }
  if(event.inputType==='insertParagraph'&&current.collapsed){
   const element=current.startContainer.nodeType===3?current.startContainer.parentElement:current.startContainer as HTMLElement;
   const heading=element?.closest('h1,h2,h3,h4,h5,h6');
   if(heading&&editor.contains(heading)){
    const before=current.cloneRange();before.selectNodeContents(heading);before.setEnd(current.startContainer,current.startOffset);
    const after=current.cloneRange();after.selectNodeContents(heading);after.setStart(current.endContainer,current.endOffset);
    if(!before.toString()||!after.toString()){
     event.preventDefault();const p=document.createElement('p');p.appendChild(document.createElement('br'));
     heading.parentNode!.insertBefore(p,!before.toString()?heading:heading.nextSibling);
     const cursor=document.createRange();cursor.selectNodeContents(p);cursor.collapse(true);selection.removeAllRanges();selection.addRange(cursor);emit();capture();
    }
   }
  }
 };
 editor.addEventListener('beforeinput',beforeInput);
 return()=>editor.removeEventListener('beforeinput',beforeInput);
 },[]);
 function end(cancel=false){if(drag.current&&!cancel&&target.current){root.current!.insertBefore(drag.current,target.current);emit();}drag.current=null;target.current=null;if(guide.current)guide.current.style.display='none';}
 return <div className={styles.draggablePaper}>
 {toolbar&&!disabled&&createPortal(<div role="toolbar" aria-label="文字の装飾" className={styles.selectionToolbar} style={{left:toolbar.left,top:toolbar.top}} onMouseDown={e=>e.preventDefault()}>
 {([{label:'本文',command:'formatBlock',value:'p'},{label:'見出し',command:'formatBlock',value:'h2'},{label:'小見出し',command:'formatBlock',value:'h3'},{label:'太字',command:'bold'},{label:'斜体',command:'italic'}]).map(item=><button type="button" key={item.label} onClick={()=>format(item.command,item.value)}>{item.label}</button>)}
 </div>,document.body)}
 <div ref={root} role="textbox" aria-label="記事本文" aria-multiline="true" contentEditable={!disabled} suppressContentEditableWarning className={`${styles.paper} ${styles.inlinePaper}`} onInput={emit}
 onPaste={e=>{e.preventDefault();document.execCommand('insertText',false,e.clipboardData.getData('text/plain'));emit();}}
 onClick={e=>{const el=e.target as HTMLElement;const button=el.closest('[data-image-delete],[data-image-ai]');if(button){const src=button.parentElement?.querySelector('img')?.getAttribute('src');if(src){if(button.hasAttribute('data-image-delete'))callbacks.current.onDelete(src);else callbacks.current.onImage(src);}}}}
 onPointerDown={e=>{const el=e.target as HTMLElement;if(el.closest('[data-ui]')){e.preventDefault();return;}const line=el.closest<HTMLElement>('[data-paid-line]');if(line&&!disabled){e.preventDefault();drag.current=line;e.currentTarget.setPointerCapture(e.pointerId);}}}
 onPointerMove={e=>{if(!drag.current)return;const choices=Array.from(root.current!.children).filter(n=>n!==drag.current);if(!choices.length)return;target.current=choices.reduce((a,b)=>Math.abs(a.getBoundingClientRect().top-e.clientY)<Math.abs(b.getBoundingClientRect().top-e.clientY)?a:b);if(guide.current){guide.current.style.display='block';guide.current.style.top=(target.current.getBoundingClientRect().top-root.current!.parentElement!.getBoundingClientRect().top)+'px';}let s:HTMLElement|null=root.current;while(s&&s.scrollHeight<=s.clientHeight+1)s=s.parentElement;if(s){const rect=s.getBoundingClientRect();if(e.clientY<Math.max(0,rect.top)+60)s.scrollTop-=24;if(e.clientY>Math.min(innerHeight,rect.bottom)-60)s.scrollTop+=24;}}}
 onPointerUp={()=>end()} onPointerCancel={()=>end(true)} onKeyDown={e=>{if(e.key==='Escape'){end(true);return;}if((e.target as HTMLElement).closest('[data-paid-line]')&&['ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();const line=root.current!.querySelector('[data-paid-line]')!;if(e.key==='ArrowUp'&&line.previousElementSibling)root.current!.insertBefore(line,line.previousElementSibling);if(e.key==='ArrowDown'&&line.nextElementSibling)root.current!.insertBefore(line,line.nextElementSibling.nextSibling);emit();}}}/>
 <div ref={guide} className={styles.dropGuide} style={{display:'none'}}/>
 </div>;
});
