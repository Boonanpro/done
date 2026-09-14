'use client';
import { useEffect, useState } from 'react';
import { EditableText } from '@/components/dan/editable';
import type { Article } from './model';
import styles from './style.module.css';
import { rememberPreviewLocation } from './navigation';

export function replyId(url:string){return /^https:\/\/(?:www\.)?(?:x\.com|twitter\.com)\/OYmpa7\/status\/(\d+)(?:[/?#].*)?$/i.exec(url.trim())?.[1];}
export function intentUrl(text:string,id?:string){const q=new URLSearchParams({text});if(id)q.set('in_reply_to',id);return 'https://x.com/intent/tweet?'+q.toString();}
const blank:NonNullable<Article['xDraft']>={post:'',articleTitle:'',articleBody:'',reply:'',postUrl:'',instruction:''};

export function XDrafts({article,onChange,onGenerate,disabled}:{article:Article;onChange:(patch:Partial<Article>)=>void;onGenerate:()=>Promise<void>;disabled:boolean}){
 const [view,setViewState]=useState<'post'|'article'|'reply'>('post');const [notice,setNotice]=useState('');
 useEffect(()=>{const restore=()=>{const value=new URL(location.href).searchParams.get('x');setViewState(value==='article'||value==='reply'?value:'post');};restore();window.addEventListener('popstate',restore);return()=>window.removeEventListener('popstate',restore);},[]);
 function setView(value:'post'|'article'|'reply'){setViewState(value);const url=new URL(location.href);url.searchParams.set('x',value);url.hash='voice-note-x-drafts';if(url.href!==location.href)history.pushState(null,'',url);rememberPreviewLocation();}
 const d=article.xDraft||blank;
 const patch=(p:Partial<typeof d>)=>onChange({xDraft:{...d,...p}});
 const reply=[d.reply,article.noteUrl].filter(Boolean).join('\n\n');const id=replyId(d.postUrl);
 async function copy(text:string){try{await navigator.clipboard.writeText(text);setNotice('コピーしました。');}catch{setNotice('コピーできませんでした。本文を選択してコピーしてください。');}}
 return <section id="voice-note-x-drafts" className={styles.notice} aria-label="Xで届ける" style={{marginTop:28,padding:20}}>
  <EditableText as="h2" editId="voice-note-x-title">Xで届ける</EditableText>
  <EditableText as="p" editId="voice-note-x-intro">投稿で気づきを伝え、コメント欄からnoteへ。原稿はここで整え、公開はXで行います。</EditableText>
  <details style={{marginBottom:18}}><summary>noteの読者を増やす行動プラン</summary><ol>
   <li>読者を「AIを実際の仕事に使いたい個人事業主・少人数の経営者」に絞る。自分が試した仕事、失敗、判断の境界を中心にする。</li>
   <li>noteを1本選び、気づきを一つに絞った投稿と、背景・具体例まで読めるX記事を作る。公式資料を使う時は日付と出典、自分の検証を添える。</li>
   <li>Xで手動公開する。投稿したURLを「コメント欄」に入れ、読む理由と関連noteのリンクを自分の返信に置く。</li>
   <li>2週間の試行目安は週3本の投稿と週1本の長文記事。同じ文の連投は避け、反応の良い論点を別の実例で深める。投稿数は運用の目安で、安全や成果の保証ではありません。</li>
   <li>週1回、表示数・プロフィール訪問・noteの閲覧と購入を見比べる。Xで伸びてもnoteが読まれなければ紹介文、読まれても売れなければ有料部分の価値を見直す。X経由と判別できない購入は合算のまま扱う。</li>
  </ol><p>今回の無料noteは信用をつくる入口です。次の有料記事では、実際に使った手順や判断基準など、読者が実行できる内容を用意します。</p><p>参考事例では通常投稿16.5万表示に対し、同じ素材のX記事が148.6万表示。X記事の末尾にもnoteへの導線がありました。ただし別時点の比較で、記事形式やリンク位置だけの効果とは断定できません。特化アカウントの急増事例には表示制限の記述もあります。</p><p><a href="https://note.com/kun1aki/n/na2d6fae42d42" target="_blank" rel="noopener noreferrer">参考：X記事からnoteへの導線</a> · <a href="https://note.com/kun1aki/n/n525e9709395e" target="_blank" rel="noopener noreferrer">参考：テーマ特化と公式資料</a></p>
  <p>収益制度は2026年9月に移行。現在の公式説明ではPremium等、認証済みフォロワー500人、直近90日の認証済み利用者によるホーム表示50万回などが条件です。自動生成・自動投稿した内容は対象外の記載があり、AI下書きを手動投稿するだけで収益対象になるとは保証できません。本人の経験と自分の言葉を軸に、申請時に条件を確認します。<a href="https://help.x.com/en/using-x/original-content-rewards" target="_blank" rel="noopener noreferrer">X公式の収益条件</a>（9月14日確認）</p></details>
  <label className={styles.field}>伝えたい切り口・修正指示<textarea rows={2} value={d.instruction} maxLength={12000} placeholder="例：自分が仕事を止めていた、という気づきを中心に" onChange={e=>patch({instruction:e.target.value})}/></label>
  <button data-edit-id="voice-note-x-generate" className={styles.primary} disabled={disabled||!article.free.trim()} onClick={()=>{if(d.generatedAt&&!window.confirm('保存済みのX原稿を作り直しますか？'))return;void onGenerate();}}>{d.generatedAt?'X原稿を作り直す':'noteからX原稿を作る'}</button>
  <div className={styles.actions} role="tablist" aria-label="Xの原稿" style={{marginTop:18}}>{(['post','article','reply'] as const).map((v,i)=><button key={v} role="tab" aria-selected={view===v} onClick={()=>setView(v)} style={view===v?{background:'#203e37',color:'white'}:{}}>{['投稿','長文記事','コメント欄'][i]}</button>)}</div>
  {view==='post'&&<div role="tabpanel"><label className={styles.field}>投稿本文<textarea rows={6} value={d.post} onChange={e=>patch({post:e.target.value})}/></label><small>{Array.from(d.post).length}文字 · 通常投稿は日本語約140文字が目安。最終的な文字数はXで確認できます。</small><div className={styles.actions}><button disabled={!d.post} onClick={()=>void copy(d.post)}>コピー</button>{d.post&&<a data-edit-id="voice-note-x-open-post" className={styles.primary} href={intentUrl(d.post)} target="_blank" rel="noopener noreferrer">本文を入れてXを開く</a>}</div></div>}
  {view==='article'&&<div role="tabpanel"><label className={styles.field}>記事タイトル<input value={d.articleTitle} onChange={e=>patch({articleTitle:e.target.value})}/></label><label className={styles.field}>長文記事の本文<textarea rows={16} value={d.articleBody} onChange={e=>patch({articleBody:e.target.value})}/></label><p>Xの長文記事はPremium等の対象プランで使えます。タイトルと本文は別の入力欄に貼り付けてください。</p><div className={styles.actions}><button disabled={!d.articleTitle} onClick={()=>void copy(d.articleTitle)}>タイトルをコピー</button><button disabled={!d.articleBody} onClick={()=>void copy(d.articleBody)}>本文をコピー</button>{d.articleBody&&<a data-edit-id="voice-note-x-open-article" href="https://x.com/compose/articles" target="_blank" rel="noopener noreferrer" onClick={()=>void copy(d.articleBody)}>本文をコピーしてXの記事画面を開く</a>}</div></div>}
  {view==='reply'&&<div role="tabpanel"><label className={styles.field}>noteを紹介するコメント<textarea rows={4} value={d.reply} onChange={e=>patch({reply:e.target.value})}/></label><p>{article.noteUrl||'noteを公開すると、ここに記事リンクが付きます。'}</p><label className={styles.field}>投稿した自分のX投稿のURL<input type="url" placeholder="https://x.com/OYmpa7/status/…" value={d.postUrl} onChange={e=>patch({postUrl:e.target.value})}/></label>{d.postUrl&&!id&&<p role="alert">@OYmpa7の投稿URLを入力してください。</p>}<div className={styles.actions}><button disabled={!d.reply||!article.noteUrl} onClick={()=>void copy(reply)}>noteリンク付きでコピー</button>{d.reply&&article.noteUrl&&id&&<a data-edit-id="voice-note-x-open-reply" className={styles.primary} href={intentUrl(reply,id)} target="_blank" rel="noopener noreferrer">コメントを入れてXの返信画面を開く</a>}</div></div>}
  <p>開いたXで投稿者が @OYmpa7 になっていることを確認してください。リンクでは投稿アカウントを固定できません。</p>
  {notice&&<p role="status">{notice}</p>}
 </section>;
}
