'use client';
import {useState,useEffect,type RefObject} from 'react';
import {Sparkles,ImagePlus,Send,Check,X,ChevronDown} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import type {Article} from './model';
import type {PaperHandle} from './inline-paper';
import styles from './style.module.css';
export function AIPanel({article,selection,imageTarget,onTarget,paper,disabled,requestError,onRun,onApply}:{article:Article;selection:string;imageTarget:string;onTarget:(s:string)=>void;paper:RefObject<PaperHandle|null>;disabled:boolean;requestError?:string;onRun:(instruction:string,intent:'text'|'image',selection:string,imageUrl:string)=>Promise<void>;onApply:(a:Partial<Article>)=>void}){
 const [prompt,setPrompt]=useState(''),[intent,setIntent]=useState<'text'|'image'>('text'),[error,setError]=useState('');
 const [open,setOpen]=useState(true);useEffect(()=>{if(imageTarget)setOpen(true);},[imageTarget]);
 const [submitting,setSubmitting]=useState(false),[applied,setApplied]=useState(false),[now,setNow]=useState(Date.now());
 useEffect(()=>{if(article.editorial?.state!=='running')return;const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[article.editorial?.state]);
 const running=article.editorial?.state==='running';
 const stale=running&&now-article.editorial!.updatedAt>=15*60_000;
 const result=article.aiResult;const imageMode=intent==='image'||Boolean(imageTarget);
 function apply(){if(!result)return;setError('');if(['title','free','paid'].some(k=>article[k as 'title'|'free'|'paid']!==result.baseline[k as 'title'|'free'|'paid'])){setError('原稿が変わっています。今の原稿で再度指示してください。');return;}
 if(result.image)paper.current?.insertImage(result.image,result.imageTarget);
 else if(result.replacement){if(!paper.current?.replaceSelection(result.replacement)){setError('書き換える範囲を選び直して、再度指示してください。');return;}}
 else if(result.free||result.paid)onApply({free:result.free||article.free,paid:result.paid||article.paid,status:'編集中'});
 onApply({aiResult:undefined});setApplied(true);onTarget('');}
 if(!open)return <button type="button" className={styles.aiLauncher} aria-label="AI編集を開く" onClick={()=>setOpen(true)}><Sparkles size={21}/></button>;
 return <section className={styles.aiPanel} aria-label="AI編集">
 <header><Sparkles size={18}/><strong>{imageMode?'GPT Image 2':'Claude Sonnet 5'}</strong><button type="button" aria-label="文章のAI" title="文章のAI" aria-pressed={!imageMode} onClick={()=>{setIntent('text');onTarget('');}}><Sparkles size={17}/></button><button type="button" aria-label="画像を生成" title="画像を生成" aria-pressed={imageMode} onClick={()=>setIntent('image')}><ImagePlus size={17}/></button><button type="button" aria-label="AI編集を折りたたむ" title="折りたたむ" onClick={()=>setOpen(false)}><ChevronDown size={17}/></button></header>
 {imageTarget?<div className={styles.aiContext}><img src={imageTarget} alt="編集する画像"/><button type="button" aria-label="画像の選択を解除" onClick={()=>onTarget('')}><X size={15}/></button></div>:selection&&<blockquote className={styles.aiContext}>{selection.slice(0,160)}</blockquote>}
 <form onSubmit={e=>{e.preventDefault();if(prompt.trim()&&!disabled&&!submitting){setSubmitting(true);setApplied(false);setError('');void onRun(prompt,imageMode?'image':'text',imageMode?'':selection,imageTarget).catch(e=>setError(e.message)).finally(()=>setSubmitting(false));}}}><textarea aria-label="AIへの指示" placeholder={imageMode?'どんな画像にしますか？':selection?'選んだ文章をどう直しますか？':'記事について相談・指示する'} value={prompt} onChange={e=>setPrompt(e.target.value)} rows={3}/><button type="submit" aria-label="AIに送信" title="送信" disabled={disabled||submitting||!prompt.trim()}><Send size={18}/></button></form>
 <div role="status" aria-live="polite" className={styles.aiStatus}>
 {submitting?'指示を送信しています…':requestError?requestError:stale?'処理状況を確認できません。応答が途切れています。':running?`AIが作成中です…（最終更新から${Math.max(0,Math.floor((now-article.editorial!.updatedAt)/1000))}秒）`:article.editorial?.state==='error'?article.editorial.message:result?(result.image||result.replacement||result.free||result.paid?'完了・原稿への適用待ちです。下の「原稿に適用」で反映できます。':'回答が届きました。'):applied?'原稿に適用しました。変更を保存してください。':'指示を入力して送信できます。'}
 {(submitting||running&&!stale)&&<progress aria-label="AIが処理中"/>}
 </div>
 {error&&<p role="alert">{error}</p>}
 {result&&<div className={styles.aiResult}><ReactMarkdown>{result.message}</ReactMarkdown>{result.image&&<img src={result.image} alt="生成した画像"/>}{(result.replacement||result.free||result.paid)&&<div className={styles.aiProposed}><ReactMarkdown>{result.replacement||[result.free,result.paid].filter(Boolean).join('\n\n')}</ReactMarkdown></div>}<div><button type="button" title="回答を閉じる" aria-label="回答を閉じる" onClick={()=>onApply({aiResult:undefined})}><X size={17}/></button>{(result.image||result.replacement||result.free||result.paid)&&<button type="button" title="原稿に適用" aria-label="原稿に適用" disabled={disabled} onClick={apply}><Check size={18}/>原稿に適用</button>}</div></div>}
 </section>;
}
