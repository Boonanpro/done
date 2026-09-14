'use client';
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { call } from './api';
import { articleOf, type Article, type Row } from './model';
import styles from './style.module.css';

function Revision({revision:r}:{revision:NonNullable<Article['revisions']>[number]}) {
 const [open,setOpen]=useState(false);
 return <details onToggle={e=>setOpen(e.currentTarget.open)}><summary>{new Date(r.savedAt).toLocaleString('ja-JP')} · {r.title}</summary>{open&&<div className={styles.paper}><ReactMarkdown>{r.free}</ReactMarkdown><div className={styles.payline}>有料にする場合の区切り</div><ReactMarkdown>{r.paid}</ReactMarkdown></div>}</details>;
}
export function ArticleHistory({row,revisions}:{row:Row;revisions:Article['revisions']}) {
 const [history,setHistory]=useState(revisions);const [open,setOpen]=useState(false);
 const [loading,setLoading]=useState(false);const [error,setError]=useState('');
 async function load(){if(loading)return;setLoading(true);setError('');try{setHistory(articleOf(await call<Row>('/dan-notion/blocks/'+row.id)).revisions||[]);}catch(e){setError((e as Error).message);}finally{setLoading(false);}}
 return <details className={styles.notice} onToggle={e=>{const show=e.currentTarget.open;setOpen(show);if(show&&!history)void load();}}><summary>前の原稿{history?`（${history.length}件）`:''}</summary>{open&&<>{loading&&<p role="status">履歴を読み込んでいます…</p>}{error&&<p role="alert">{error}<button onClick={()=>void load()}>再試行</button></p>}{history?.length===0&&<p>前の原稿はありません。</p>}{history?.map((r,i)=><Revision key={i} revision={r}/>)}</>}</details>;
}
