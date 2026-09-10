'use client';
import { useEffect, useRef, useState } from 'react';
import { Mic, Square, Upload, Plus, FileText, ArrowRight, RefreshCw, LockKeyhole, Send } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { EditableText } from '@/components/dan/editable';
import { useSetupGate } from '@/hooks/use-setup-gate';
import { api } from '@/lib/api-client';
import { articleOf, isEmptyArticle, publishRequest, emptyArticle, ROOM_ID, type Row, type Article } from './model';
import { startEditorial, call, findWorkspace, saveArticle, uploadAudio } from './api';
import styles from './style.module.css';
import { RecordedAudio } from './recorded-audio';
import { InputLevel } from './input-level';

export function PageBody() {
 const [root,setRoot]=useState<Row>();const [rows,setRows]=useState<Row[]>([]);const [selected,setSelected]=useState<Row>();
 const [draft,setDraft]=useState<Article>(emptyArticle);const [tab,setTab]=useState('つくる');const [busy,setBusy]=useState(false);
 const editing=draft.editorial?.state==='running' && Date.now()-draft.editorial.updatedAt<15*60_000;
 const [dirty,setDirty]=useState(false);const [message,setMessage]=useState('');const [error,setError]=useState('');
 const [recording,setRecording]=useState(false);const [confirm,setConfirm]=useState<'publish'|'delete'|'empty'|null>(null);
 const [deleteTarget,setDeleteTarget]=useState<Row>();const actionLock=useRef(false);
 const emptyRows=rows.filter(r=>isEmptyArticle(articleOf(r)));
 const [preview,setPreview]=useState(true);const [loading,setLoading]=useState(true);const recorder=useRef<MediaRecorder|null>(null);
 const fileInput=useRef<HTMLInputElement>(null);const [audioBlob,setAudioBlob]=useState<Blob>();
 const [inputs,setInputs]=useState<MediaDeviceInfo[]>([]);
 const [inputId,setInputId]=useState('');const [activeInput,setActiveInput]=useState('');const [meterStream,setMeterStream]=useState<MediaStream|null>(null);
 async function scanInputs(){const list=(await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==='audioinput'&&d.deviceId);setInputs(list);return list;}
 function chooseInput(id:string){setInputId(id);try{localStorage.setItem('voice-note-microphone-choice-v2',id);}catch{}}
 useEffect(()=>{try{setInputId(localStorage.getItem('voice-note-microphone-choice-v2')||'');}catch{}const refreshInputs=()=>{void scanInputs().catch(()=>{});};refreshInputs();navigator.mediaDevices?.addEventListener('devicechange',refreshInputs);return()=>navigator.mediaDevices?.removeEventListener('devicechange',refreshInputs);},[]);
 const [inputError,setInputError]=useState('');
 const [inputRetry,setInputRetry]=useState(0);
 const monitoring=Boolean(root&&selected&&tab==='つくる');
 useEffect(()=>{
   if(!monitoring)return;
   let cancelled=false;let current:MediaStream|undefined;
   setMeterStream(null);setInputError('');
   void (async()=>{
     try{
       current=await navigator.mediaDevices.getUserMedia({audio:inputId?{deviceId:{exact:inputId}}:{deviceId:{ideal:'default'}}});
       if(cancelled){current.getTracks().forEach(t=>t.stop());return;}
       setMeterStream(current);setActiveInput(current.getAudioTracks()[0]?.label||'端末の標準入力');
       current.getAudioTracks()[0]?.addEventListener('ended',()=>{if(!cancelled){setMeterStream(null);setInputError('入力機器との接続が切れました。入力を選び直してください。');}});
       await scanInputs();
     }catch(e){if(!cancelled){setMeterStream(null);setInputError((e as DOMException).name==='NotAllowedError'?'マイクの使用を許可してください。':'入力を開始できません。機器の接続と選択を確認してください。');}}
   })();
   return()=>{cancelled=true;current?.getTracks().forEach(t=>t.stop());};
 },[monitoring,inputId,inputRetry]);
 const gate=useSetupGate(async()=>Boolean(await findWorkspace()));
 async function refresh(selectId?:string){setLoading(true);setError('');try{const w=await findWorkspace();if(!w)throw new Error('本人アカウントで編集室を開いてください。');setRoot(w);const list=await call<Row[]>('/dan-notion/blocks/'+w.id+'/children');setRows(list);if(selectId){const r=list.find(x=>x.id===selectId);if(r){setSelected(r);setDraft(articleOf(r));setDirty(false);}}}catch(e){setError((e as Error).message);}finally{setLoading(false);}}
 useEffect(()=>{void refresh();return()=>{recorder.current?.stream.getTracks().forEach(t=>t.stop());};},[]);
 useEffect(()=>{const fn=(e:BeforeUnloadEvent)=>{if(dirty||audioBlob){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',fn);return()=>window.removeEventListener('beforeunload',fn);},[dirty,audioBlob]);
 const update=(patch:Partial<Article>)=>{setDraft(v=>({...v,...patch}));setDirty(true);};
 async function run(fn:()=>Promise<void>){if(actionLock.current||busy||editing)return;actionLock.current=true;setBusy(true);setError('');setMessage('');try{await fn();}catch(e){setError((e as Error).message);}finally{actionLock.current=false;setBusy(false);}}
 async function save(){if(!selected)throw new Error('記事を作成してください。');const r=await saveArticle(selected,draft);setSelected(r);setRows(v=>v.map(x=>x.id===r.id?r:x));setDirty(false);return r;}
 async function create(){await run(async()=>{if(!root)throw new Error('保存先に接続してください。');if(recording||audioBlob)throw new Error('録音を保存してから記事を切り替えてください。');let list=rows;if(selected&&dirty){const saved=await save();list=rows.map(r=>r.id===saved.id?saved:r);}const unused=list.find(r=>isEmptyArticle(articleOf(r)));if(unused){setSelected(unused);setDraft(articleOf(unused));setDirty(false);setTab('つくる');return;}const a=emptyArticle();const r=await call<Row>('/dan-notion/blocks','POST',{type:'page',parent_id:root.id,properties:{title:a.title,kind:'voice_note_article',article:a},content:[]});setRows(v=>[...v,r]);setSelected(r);setDraft(a);setDirty(false);setTab('つくる');});}
 function requestDelete(row:Row){setDeleteTarget(row);setConfirm('delete');}
 async function removeArticles(){await run(async()=>{
  if(recording||audioBlob)throw new Error('録音を保存してから削除してください。');
  const targets=confirm==='empty'?emptyRows:deleteTarget?[deleteTarget]:[];
  let count=0;
  for(const targetRow of targets){
   const current=await call<Row>('/dan-notion/blocks/'+targetRow.id);
   const a=articleOf(current);
   if(a.editorial?.state==='running'&&Date.now()-a.editorial.updatedAt<15*60_000)throw new Error('作成中の記事は削除できません。');
   if(confirm==='empty'&&(!isEmptyArticle(a)||(selected?.id===current.id&&dirty)))continue;
   await call('/dan-notion/blocks/'+current.id,'DELETE');
   setRows(v=>v.filter(r=>r.id!==current.id));
   if(selected?.id===current.id){setSelected(undefined);setDraft(emptyArticle());setDirty(false);}
   count++;
  }
  setConfirm(null);setDeleteTarget(undefined);setMessage(`${count}件の記事を削除しました。`);
 });}
 async function pick(row:Row){await run(async()=>{if(recording||audioBlob)throw new Error('録音を保存してから記事を切り替えてください。');if(selected&&dirty)await save();setSelected(row);setDraft(articleOf(row));setDirty(false);setTab('つくる');});}
 async function attach(file:File){await run(async()=>{if(!selected)throw new Error('記事を作成してください。');const audio=await uploadAudio(file);const a={...draft,audio:[...draft.audio,audio]};const r=await saveArticle(selected,a);setSelected(r);setRows(v=>v.map(x=>x.id===r.id?r:x));setDraft(a);setDirty(false);setAudioBlob(undefined);setMessage('音声を保存しました。「記事に整える」で制作を始めます。');});}
 async function record(){
 if(recording){recorder.current?.stop();return;}
 await run(async()=>{
   if(!meterStream?.active)throw new Error('入力の準備ができていません。マイクの許可と入力機器を確認してください。');
   const recordingStream=meterStream.clone();
   try{
     const r=new MediaRecorder(recordingStream);recorder.current=r;const chunks:Blob[]=[];
     r.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
     r.onstop=()=>{setRecording(false);setAudioBlob(new Blob(chunks,{type:r.mimeType}));recordingStream.getTracks().forEach(t=>t.stop());};
     r.onerror=()=>{recordingStream.getTracks().forEach(t=>t.stop());setRecording(false);setError('録音が中断しました。');};
     r.start(1000);setRecording(true);
   }catch(e){recordingStream.getTracks().forEach(t=>t.stop());throw e;}
 });}
 async function send(kind:'edit'|'publish'){if(kind==='edit'){await run(async()=>{const row=await save();const updated=await startEditorial(row.id);setSelected(updated);setDraft(articleOf(updated));setRows(v=>v.map(x=>x.id===updated.id?updated:x));setDirty(false);setMessage('');});return;}await run(async()=>{if(kind==='publish'&&(!draft.title.trim()||!draft.free.trim()||(draft.price>0&&!draft.paid.trim())||draft.questions.length))throw new Error('本文と確認事項を解消してから投稿してください。');const row=await save();setConfirm(null);setMessage('ダンがこのチャットで対応しています。');await api.sm.sendMessageStream({message:publishRequest(row.id),session_id:ROOM_ID,client_message_id:crypto.randomUUID()},{onError:e=>setError(e),onComplete:()=>{void refresh(row.id);},onAIMessage:m=>setMessage(m.content),onInterrupted:()=>setMessage('接続が切れました。このチャットの処理状況を確認してから更新してください。')});});}
 useEffect(()=>{if(!selected||!editing)return;let stopped=false;const id=selected.id;const poll=async()=>{try{const row=await call<Row>('/dan-notion/blocks/'+id);if(!stopped){setError('');setSelected(row);setDraft(articleOf(row));setRows(v=>v.map(x=>x.id===id?row:x));setDirty(false);}}catch{if(!stopped)setError('進捗を取得できません。接続が戻ると再確認します。');}};const timer=setInterval(()=>{void poll();},2000);return()=>{stopped=true;clearInterval(timer);};},[selected?.id,editing]);
 const month=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Tokyo'}).slice(0,7);
 const measured=rows.map(articleOf).filter(a=>a.salesMonth===month&&a.checkedAt);const basis=root?.properties.target_basis==='gross'?'gross':'received';const amount=measured.reduce((n,a)=>n+a[basis],0);const target=Number(root?.properties.monthly_target)||300000;
 return <main className={styles.app}>
 <header className={styles.header}><div className={styles.brand}><FileText size={23}/><EditableText as="span" editId="voice-note-home-brand">話して、noteに。</EditableText></div><EditableText as="span" editId="voice-note-home-private" className={styles.private}><LockKeyhole size={14}/>自分だけの編集室</EditableText></header>
 <div className={styles.top}><div><EditableText as="p" editId="voice-note-home-eyebrow" className={styles.eyebrow}>あなたの経験を、誰かの役に立つ記事へ。</EditableText><EditableText as="h1" editId="voice-note-home-heading">考えは、話すところから。</EditableText><EditableText as="p" editId="voice-note-home-lead" className={styles.lead}>まとまっていなくて大丈夫。話した内容を残して、ダンと記事に仕上げます。</EditableText></div><div className={styles.goal}><EditableText as="small" editId="voice-note-home-goal-label">今月の{basis==='gross'?'売上':'受取額'} / 目標</EditableText><EditableText as="strong" editId="voice-note-home-goal-value">{measured.length?'¥'+amount.toLocaleString():'未集計'} <span>/ ¥{target.toLocaleString()}</span></EditableText><progress max={target} value={amount}/><EditableText as="small" editId="voice-note-home-goal-help">{measured.length?'確認済みの実績を集計':'売上を確認したら「実績」に記録'}</EditableText></div></div>
 <nav className={styles.tabs} aria-label="編集室のメニュー">{['つくる','記事一覧','実績'].map(t=><EditableText as="button" editId={`voice-note-home-tab-${t}`} key={t} aria-current={tab===t?'page':undefined} onClick={()=>setTab(t)}>{t}</EditableText>)}<EditableText as="button" editId="voice-note-home-refresh" className={styles.refresh} disabled={busy||editing||dirty||recording||Boolean(audioBlob)} onClick={()=>void refresh(selected?.id)}><RefreshCw size={15}/>更新</EditableText></nav>
 <div aria-live="polite">{error&&<p role="alert" data-edit-id="voice-note-home-error" className={styles.error}>{error}</p>}{message&&<p data-edit-id="voice-note-home-result" className={styles.notice}>{message}</p>}</div>
 {loading?<div className={styles.empty}>編集室を読み込んでいます…</div>:!root?<div className={styles.empty}><EditableText as="h2" editId="voice-note-home-auth-title">ダンの本人アカウントで開く編集室です。</EditableText><EditableText as="p" editId="voice-note-home-auth-copy">公開ページに記事本文は表示されません。</EditableText><EditableText as="button" editId="voice-note-home-retry" onClick={()=>void refresh()}>接続を再確認</EditableText></div>:<>
 {tab==='つくる'&&<div className={styles.workspace}><aside className={styles.side}><button className={styles.primary} disabled={busy||editing||recording||Boolean(audioBlob)} onClick={()=>void create()}><Plus size={17}/>新しい記事</button><small>記事の素材と下書き</small>{rows.map(r=><div className={styles.articleItem} key={r.id}><button className={selected?.id===r.id?styles.chosen:styles.item} onClick={()=>void pick(r)} disabled={busy||editing||recording||Boolean(audioBlob)}><span>{articleOf(r).title}</span><small>{articleOf(r).status}</small></button><button aria-label={`${articleOf(r).title}を削除`} disabled={busy||editing||recording||Boolean(audioBlob)} onClick={()=>requestDelete(r)}>削除</button></div>)}<div className={styles.hint}><strong>こんな話から</strong><p>最近、面倒だったこと。<br/>試して失敗したこと。<br/>前より楽になった工夫。</p></div></aside>
 {!selected?<section className={styles.start}><div className={styles.mic}><Mic size={34}/></div><EditableText as="h2" editId="voice-note-home-start">いつもの話が、記事の種になる。</EditableText><EditableText as="p" editId="voice-note-home-start-copy">音声を録る。ファイルを追加する。<br/>このチャットで話す。どこからでも始められます。</EditableText><EditableText as="button" editId="voice-note-home-first-article" className={styles.primary} onClick={()=>void create()} disabled={busy||editing}>最初の記事をつくる<ArrowRight size={17}/></EditableText><div className={styles.flow}><span>01 話す</span><span>02 記事に整える</span><span>03 確認して投稿</span></div></section>:<fieldset className={styles.editor} disabled={busy||editing}>
 {draft.editorial&&<div role="status" aria-live="polite" style={{padding:12,background:'#eef7f4',borderRadius:8}}>{draft.editorial.state==='running'&&!editing?'処理の応答が途切れました。再試行してください。':draft.editorial.message}{editing&&<progress aria-label="記事を作成中" style={{display:'block',width:'100%',marginTop:8}}/>}</div>}<div className={styles.editorTop}><span>{draft.status}</span><span>{dirty?'未保存の変更があります':'保存済み'}</span><button disabled={busy||editing||!dirty} onClick={()=>void run(async()=>{await save();setMessage('保存しました。');})}>保存</button></div>
 <label className={styles.field}>タイトル<input value={draft.title} onChange={e=>update({title:e.target.value})}/></label>
 <div role="group" aria-label="録音に使う入力" style={{display:'flex',flexWrap:'wrap',gap:8,marginTop:16}}>
 <EditableText as="button" editId="voice-note-input-default" type="button" aria-pressed={!inputId} disabled={recording} onClick={()=>{chooseInput('');setInputRetry(v=>v+1);}} style={{background:!inputId?'#07856d':undefined,color:!inputId?'white':undefined}}>端末の標準入力</EditableText>
 {inputs.filter(d=>d.deviceId!=='default'&&d.deviceId!=='communications').map((d,i)=><button key={d.deviceId} type="button" aria-pressed={inputId===d.deviceId} disabled={recording} onClick={()=>{chooseInput(d.deviceId);setInputRetry(v=>v+1);}} style={{background:inputId===d.deviceId?'#07856d':undefined,color:inputId===d.deviceId?'white':undefined,overflowWrap:'anywhere'}}>{d.label||`入力 ${i+1}`}</button>)}
 </div><InputLevel stream={meterStream}/>{inputError&&<p role="alert">{inputError}</p>}{recording&&<p role="status">録音中の入力：{activeInput}</p>}
 <details open={!draft.free}><summary>話したこと・音声</summary><div className={styles.actions}><button onClick={()=>void record()} disabled={busy||editing||Boolean(audioBlob)||(!recording&&!meterStream)}>{recording?<Square size={16}/>:<Mic size={16}/>} {recording?'録音を止める':'録音する'}</button><button disabled={busy||editing||recording} onClick={()=>fileInput.current?.click()}><Upload size={16}/>音声を追加</button><input ref={fileInput} type="file" accept="audio/*,.webm,.mp4" hidden onChange={e=>{const f=e.target.files?.[0];if(f)void attach(f);e.target.value='';}}/></div>
 {audioBlob&&<div className={styles.audio}><RecordedAudio blob={audioBlob}/><button disabled={busy||editing} onClick={()=>void attach(new File([audioBlob],'録音.'+(audioBlob.type.includes('mp4')?'m4a':'webm'),{type:audioBlob.type}))}>この録音を保存</button><button disabled={busy||editing} onClick={()=>setAudioBlob(undefined)}>取り直す</button></div>}
 {draft.audio.map(a=><div key={a.url} className={styles.audio}><small>{a.name}</small>{a.url?.trim()?<audio controls src={a.url}/>:<span>音声の保存先が見つかりません。</span>}</div>)}
 <label className={styles.field}>話した内容<textarea rows={5} value={draft.transcript} placeholder="思いついた順で、そのまま。音声だけでも記事にできます。" onChange={e=>update({transcript:e.target.value})}/></label><button className={styles.primary} disabled={busy||editing||recording||Boolean(audioBlob)||(!draft.transcript.trim()&&!draft.audio.length)} onClick={()=>void send('edit')}>記事に整える<ArrowRight size={16}/></button></details>
 {draft.questions.length>0&&<div className={styles.notice}><strong>記事を仕上げるための確認</strong>{draft.questions.map(q=><p key={q}>{q}</p>)}</div>}
 <div className={styles.editorTop}><h2>記事の仕上がり</h2><button onClick={()=>setPreview(!preview)}>{preview?'本文を編集':'読みやすさを確認'}</button></div>
 {preview?<div className={styles.paper}>{draft.free?<ReactMarkdown>{draft.free}</ReactMarkdown>:<p className={styles.placeholder}>記事ができると、ここで見出しや太字を含めて確認できます。</p>}{draft.price>0&&<div className={styles.payline}><LockKeyhole size={15}/>ここから有料 · ¥{draft.price.toLocaleString()}</div>}{draft.paid&&<ReactMarkdown>{draft.paid}</ReactMarkdown>}</div>:<><label className={styles.field}>無料で読める部分<textarea rows={10} value={draft.free} onChange={e=>update({free:e.target.value,status:'編集中'})}/></label><div className={styles.payline}>この下から有料部分</div><label className={styles.field}>購入した人が読める部分<textarea rows={10} value={draft.paid} onChange={e=>update({paid:e.target.value,status:'編集中'})}/></label><small>見出しは ##、強調は **太字** で囲みます。</small></>}
 <div className={styles.settings}><label className={styles.field}>販売価格（円・0で無料）<input type="number" min="0" step="1" value={draft.price} onChange={e=>update({price:Number(e.target.value)})}/></label><label className={styles.field}>公開希望日時（日本時間・空欄で今すぐ）<input type="datetime-local" value={draft.scheduledAt} onChange={e=>update({scheduledAt:e.target.value})}/></label></div>
 <div className={styles.footer}><button onClick={()=>requestDelete(selected)} disabled={busy||editing||recording}>削除</button><button className={styles.primary} disabled={busy||editing||recording||Boolean(audioBlob)||!draft.free.trim()||draft.questions.length>0} onClick={()=>setConfirm('publish')}><Send size={16}/>投稿内容を確認</button></div></fieldset>}</div>}
 {tab==='記事一覧'&&<section className={styles.list}><h2>すべての記事 <small>{rows.length}本</small></h2>{emptyRows.length>0&&<button disabled={busy||editing||recording||Boolean(audioBlob)||dirty} onClick={()=>setConfirm('empty')}>空の記事をまとめて削除（{emptyRows.length}件）</button>}{!rows.length?<p>まだ記事はありません。「つくる」から音声を追加できます。</p>:rows.map(r=>{const a=articleOf(r);return <div key={r.id} className={styles.articleItem}><button className={styles.listRow} onClick={()=>void pick(r)}><FileText size={20}/><span><strong>{a.title}</strong><small>{a.status} · {a.price?'¥'+a.price.toLocaleString():'無料'}{a.scheduledAt?' · 公開希望 '+a.scheduledAt.replace('T',' '):''}</small></span><ArrowRight size={17}/></button><button disabled={busy||editing||recording||Boolean(audioBlob)} aria-label={`${a.title}を削除`} onClick={()=>requestDelete(r)}>削除</button></div>;})}</section>}
 {tab==='実績'&&<section className={styles.list}><h2>月30万円までの記録</h2><p className={styles.lead}>noteで確認した数字を保存します。未入力の実績を売上ゼロとは扱いません。</p><div className={styles.settings}><label className={styles.field}>目標の基準<select value={basis} disabled={busy||editing} onChange={e=>void run(async()=>{const r=await call<Row>('/dan-notion/blocks/'+root.id,'PATCH',{properties:{...root.properties,target_basis:e.target.value}});setRoot(r);})}><option value="received">手数料を引いた受取額</option><option value="gross">手数料を引く前の売上</option></select></label><div className={styles.calculation}><strong>¥1,000 × 300件 = 売上 ¥300,000</strong><small>価格の例です。受取額は決済方法などで変わります。</small></div></div>
 {selected?<><h3>{draft.title}</h3><div className={styles.settings}><label className={styles.field}>集計月<input type="month" value={draft.salesMonth} onChange={e=>update({salesMonth:e.target.value,checkedAt:'',purchases:0,gross:0,received:0})}/></label>{(['purchases','gross','received'] as const).map((key,i)=><label key={key} className={styles.field}>{['購入件数','売上（円）','受取額（円）'][i]}<input type="number" min="0" value={draft[key]} onChange={e=>update({[key]:Number(e.target.value)})}/></label>)}</div><label className={styles.field}>公開記事URL<input type="url" value={draft.noteUrl} onChange={e=>update({noteUrl:e.target.value})}/></label><button className={styles.primary} disabled={busy||editing} onClick={()=>void run(async()=>{const a={...draft,checkedAt:new Date().toISOString()};const r=await saveArticle(selected,a);setDraft(a);setSelected(r);setRows(v=>v.map(x=>x.id===r.id?r:x));setDirty(false);setMessage('実績を保存しました。');})}>確認した実績を保存</button></>:<p>「記事一覧」で記事を選ぶと、実績を入力できます。</p>}</section>}
 </>}
 {confirm&&<div className={styles.backdrop}><div role="dialog" aria-modal="true" aria-labelledby="confirm-title" className={styles.dialog}><h2 id="confirm-title">{confirm==='empty'?`空の記事${emptyRows.length}件を削除しますか？`:confirm==='delete'?'この記事を削除しますか？':'この内容をnoteに投稿します'}</h2><p>{confirm==='empty'?'音声・本文・設定のある記事は残します。':confirm==='delete'?articleOf(deleteTarget!).title:draft.title}</p>{confirm==='publish'&&<><p>{draft.price?'有料 ¥'+draft.price.toLocaleString():'無料'} · {draft.scheduledAt?draft.scheduledAt.replace('T',' ')+'（日本時間）':'今すぐ公開'}</p><p>本文・価格・有料ラインを確認したうえで、ダンに投稿を依頼します。</p></>}<div className={styles.actions}><button onClick={()=>setConfirm(null)}>戻る</button><button className={styles.primary} disabled={busy||editing} onClick={()=>{if(confirm==='publish'){void send('publish');}else{void removeArticles();}}}>{confirm!=='publish'?'削除する':'この内容で投稿を依頼'}</button></div></div></div>}
 <span hidden>{gate.status}</span></main>;
}
