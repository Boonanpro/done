/* GPT-Live owns speech and client delegation. No VAD-to-request loop. */
let liveConnection=null;
let livePausedContext=null,liveClosing=null;
const liveDeferredReports=[];
let liveAutoConnecting=false;
function liveReplyActivity(session=liveConnection){
 if(session?.automaticReport)session.idleSince=Date.now();
}
async function liveAutoDisconnect(){
 const session=liveConnection;
 if(!session?.automaticReport||!session.idleSince||session.responsePending||audioPlaying||busy||active||activeNotice||reasonRunning||(currentWorkLine&&!pendingQuestion))return;
 if(Date.now()-session.idleSince<30000)return;
 record('live_auto_disconnect',{reason:'no_reply_30_seconds'});
 if(micOn)await toggleMic();
}
function liveEditingContext(){return liveConnection?.editContext||livePausedContext||context;}
function muteLiveInput(){
 mic?.getTracks().forEach(t=>t.enabled=false);
 if(liveConnection){liveConnection.muteRequested=true;liveConnection.quietSince=Date.now();}
 record('live_input_muted',{output_continues:true});
}
function finishMutedLive(){
 const session=liveConnection;
 if(!session?.muteRequested||micOn)return;
 if(audioPlaying||busy||activeNotice||reasonRunning||session.responsePending){session.quietSince=Date.now();return;}
 if(Date.now()<(session.awaitingSpeechUntil||0)||Date.now()-(session.quietSince||0)<3000)return;
 pauseLive();
}
function pauseLive(){
 const session=liveConnection;
 if(session){session.paused=true;livePausedContext=structuredClone(session.editContext);}
 if(activeNotice){completionNotices.unshift(activeNotice);activeNotice=null;saveConversation();}
 audioPlaying=false;
 closeLiveTransport();
 record('live_voice_paused',{production_continues:true});
}
const liveCalls=new Set();
// Current facts are available on demand; polling does not request speech.
let liveProductionFacts=null;
let livePresentationFacts=null;
function liveFacts(){
 const editing=liveEditingContext(),room=editing?.room_id;
 return {observed_at_ms:Date.now(),conversation_work:liveConnection?.work||null,
  operations:typeof visibleToolWork==='undefined'?[]:Array.from(visibleToolWork.values()),
  production:liveProductionFacts?.room_id===room&&(!liveProductionFacts.content_id||liveProductionFacts.content_id===editing?.content_id)?liveProductionFacts:null,
  presentation:livePresentationFacts?.room_id===room&&livePresentationFacts?.content_id===editing?.content_id?livePresentationFacts:null};
}
function liveBackendMessage(b,event){
 const text=event.text?.trim();if(!text)return;
 const seen=b.liveMessages||(b.liveMessages=new Set());
 const key=event.id||text;if(seen.has(key))return;seen.add(key);
 const data={kind:'backend_message',phase:event.phase||'answer',text};
 if(b.pendingPresentationReport){b.pendingPresentationExplanation=data;return;}
 if(liveConnection?.started&&liveConnection.editContext?.room_id===b.context.room_id&&liveConnection.editContext?.content_id===b.context.content_id){
  // Display acknowledgement already invited speech for this result. Preserve
  // the final reasoning as context without issuing a second speaking request.
  liveAppend(event.phase==='commentary'||b.livePresentationReported?'thinking':'commentary',JSON.stringify(data),b.liveSession===liveConnection?b.liveDelegation||null:null);
 }else if(event.phase!=='commentary')liveDeferredReports.push({room_id:b.context.room_id,content_id:b.context.content_id,text});
 record('live_backend_message_delivered',{message_id:event.id,phase:event.phase,turn_id:b.turn_id});
}
function livePresentationItem(i){
 const item={id:i.id,title:i.title,kind:i.kind,note:i.note,url:i.source_url||i.url,start:i.start,end:i.end,library_id:i.library_id,observation_basis:i.observation_basis};
 if(i.scene)item.appearance={duration:i.scene.duration,description:i.scene.description,params:i.scene.params};
 if(i.composition){
  const c=i.composition,text=c.layers.filter(l=>l.type==='text');
  item.appearance={background:c.background,duration:c.duration,text_colors:[...new Set(text.map(l=>l.color))],font_sizes:[...new Set(text.map(l=>l.fontSize))],text:text.map(l=>l.text)};
 }
 return item;
}
function queueReferenceReport(b,facts,session){
 if(session.referenceObservedInput===session.rows.user?.id){
  // Native Live already received this comparison while listening. A later
  // delegation acknowledgement must not prompt a second explanation.
  sendReferenceFacts(facts,b.liveDelegation||null);return;
 }
 session.referenceReport={b,facts,inputId:session.rows.user?.id,basisText:session.visualPresented?.text||session.rows.user?.text};
 flushReferenceReport(session);
}
function sendReferenceFacts(facts,delegation=null){
 liveAppend('thinking',JSON.stringify({kind:'current_reference_comparison',id:facts.id,revision:facts.revision,
   count:facts.items?.length||0,source:'existing_library',created:0,modified:0}),delegation);
 for(const [position,item] of (facts.items||[]).entries()){
  const detail={comparison_id:facts.id,position:position+1,
    evidence:item.observation_basis||(item.library_id?.startsWith('yt-')?'publisher_metadata_not_watched':'reference_description'),
    title:item.title,description:item.note||item.appearance?.description||item.title||''};
  while(new TextEncoder().encode(JSON.stringify(detail)).length>460&&detail.description.length)detail.description=detail.description.slice(0,-1);
  while(new TextEncoder().encode(JSON.stringify(detail)).length>460&&detail.title.length)detail.title=detail.title.slice(0,-1);
  liveAppend('thinking',JSON.stringify(detail),delegation);
 }
 if(facts.discovery)sendDiscoveryFacts(facts.discovery,delegation,facts.items);
}
function sendExecutionFacts(session=liveConnection){
 if(!session?.started)return;
 const facts=liveFacts(),production=facts.production;
 liveAppend('thinking',JSON.stringify({kind:'production_snapshot',known:!!production,
   observed_at_ms:production?.observed_at_ms,active_count:production?.active?.length??null,
   conversation_status:session.work?.status||null,
   meaning:'Job records, separate from conversational handoffs. Only an actual stop result confirms cancellation. This is silent context, not a request to narrate.'}));
 for(const job of [...(production?.active||[]),...(production?.recent||[])]){
  const summary={kind:'active_production_job',id:job.id,status:job.status,request:(job.request||'').slice(0,80)};
  liveAppend('thinking',JSON.stringify(summary));
 }
}
function sendDiscoveryFacts(discovery,delegation=null,items=[]){
 if(discovery.comparison?.reason!=='evidenced_contrast')return;
 // Silent context, never a request to narrate the router's internal state.
 liveAppend('thinking',JSON.stringify({kind:'creative_discovery',change:discovery.change,
  next:discovery.next_axis,axis:discovery.axis_label,
  evidence:discovery.comparison?.reason||'conversation_only',
  instruction:'Use original user words. Only evidenced_contrast supports claims about visual differences. Otherwise let the user judge the references. Reuse is not a new example or progress. Do not announce this state.'}),delegation);
 for(const [axis,belief] of Object.entries(discovery.beliefs||{})){
  if(belief.preferred||belief.avoid)liveAppend('thinking',JSON.stringify({kind:'current_preference',axis,
    preferred:belief.preferred,avoid:belief.avoid,basis:'tentative_reading_of_user_words'}),delegation);
 }
 for(const side of discovery.comparison?.sides||[]){
  const position=items.findIndex(i=>i.library_id===side.id);
  if(position>=0)liveAppend('thinking',JSON.stringify({kind:'comparison_evidence',position:position+1,
   axis:discovery.axis_label,value:side.label,reused:(discovery.reused_ids||[]).includes(side.id)}),delegation);
 }
}
function cancelReferenceReportForInput(session,inputId){
 if(session.referenceReport?.inputId!==inputId)return;
 clearTimeout(session.referenceReportTimer);session.referenceReportTimer=null;
 session.referenceReport=null;
 record('reference_report_superseded',{input_id:inputId});
}
function flushReferenceReport(session){
 clearTimeout(session.referenceReportTimer);session.referenceReportTimer=null;
 const report=session.referenceReport;if(!report)return;
 if(session!==liveConnection||!session.started||session.rows.user?.id!==report.inputId){session.referenceReport=null;return;}
 if(report.basisText!==session.rows.user?.text){session.referenceReport=null;return;}
 const now=Date.now(),end=session.rows.user?.end;
 // Live's word timestamps describe the original input, not when a delayed
 // transcript packet arrived. Wait for transcription to catch the microphone.
 const behind=session.lastInputSound&&Number.isFinite(session.inputTranscriptOffset)&&Number.isFinite(end)&&
   end+session.inputTranscriptOffset<session.lastInputSound-200;
 if(audioPlaying||now-(session.lastInputSound||0)<700||now-(session.lastVisualTranscriptAt||0)<600||behind){
  if(now-(session.referenceWaitLogged||0)>1000){
   session.referenceWaitLogged=now;
   record('reference_report_waiting',{audio_playing:audioPlaying,input_quiet_ms:now-(session.lastInputSound||0),transcript_quiet_ms:now-(session.lastVisualTranscriptAt||0),transcript_behind:!!behind});
  }
  session.referenceReportTimer=setTimeout(()=>flushReferenceReport(session),100);
  session.referenceReportTimer?.unref?.();return;
 }
 session.referenceReport=null;
 const {b,facts,inputId}=report;
 if(facts.id!==livePresentationFacts?.id||facts.revision!==livePresentationFacts?.revision)return;
 const duplicate=session.referenceSpokenInput===inputId;
 // Each append is a complete fact. Splitting a large presentation JSON across
 // many small appends exposed incomplete counts/descriptions while speaking.
 if(!b.referenceFactsSent)sendReferenceFacts(facts,b.liveDelegation||null);
 liveAppend(duplicate?'thinking':'commentary',JSON.stringify({kind:'presentation_available',id:facts.id,revision:facts.revision,count:facts.items?.length||0}),b.liveDelegation||null);
 session.referenceSpokenInput=inputId;
 record('reference_report_delivered',{presentation_id:facts.id,revision:facts.revision,input_id:inputId,speaking:!duplicate});
}
function livePresentationSnapshot(facts,delegation=null){
 liveAppend('thinking',JSON.stringify({kind:'presentation_available',id:facts.id,revision:facts.revision,count:facts.items?.length||0,display_ok:facts.display?.ok}),delegation);
 for(const item of facts.items||[]){
  const detail={kind:'displayed_item',id:item.id,title:item.title||'',duration:item.appearance?.duration};
  while(new TextEncoder().encode(JSON.stringify(detail)).length>460&&detail.title.length)detail.title=detail.title.slice(0,-1);
  liveAppend('thinking',JSON.stringify(detail),delegation);
 }
}
function livePresented(b,presentation,display,operation=null){
 if(livePresentationFacts?.id===presentation.id&&livePresentationFacts.revision===(presentation.revision||0))return;
 b.livePresentationReported=true;
 livePresentationFacts={room_id:b.context.room_id,content_id:b.context.content_id,id:presentation.id,revision:presentation.revision||0,display,
  operation:b.referenceOperation||'presentation',discovery:b.discovery,items:presentation.items.map(livePresentationItem)};
 if(b.referenceOperation==='selected_existing_library_examples_without_modification'){
  livePresentationFacts.result={source:'existing_library',created:0,modified:0,displayed:presentation.items.length};
 }
 if(liveConnection?.started&&liveConnection.editContext?.room_id===b.context.room_id&&liveConnection.editContext?.content_id===b.context.content_id){
  if(b.referenceOperation==='selected_existing_library_examples_without_modification'){
   // Perception cannot wait for the end of Dan's speech: otherwise it may
   // describe an imagined comparison while the actual cards are already up.
   sendReferenceFacts(livePresentationFacts,b.liveDelegation||null);b.referenceFactsSent=true;
   if(b.livePreview||audioPlaying){
    // Native Live hears the whole utterance; transcript silence is not a turn
    // boundary. Keep its visual perception current without forcing it to speak.
    // An ongoing response can already incorporate these facts; queuing another
    // invitation after that response repeats the same comparison.
    liveConnection.referenceObservedInput=liveConnection.rows.user?.id;
    record('reference_preview_observed',{presentation_id:presentation.id,revision:presentation.revision||0});
    record('live_presentation_delivered',{presentation_id:presentation.id,turn_id:b.turn_id});return;
   }
   queueReferenceReport(b,livePresentationFacts,liveConnection);
   record('live_presentation_delivered',{presentation_id:presentation.id,turn_id:b.turn_id});return;
  }
  // Speech-in-progress previews remain available via liveFacts, but are not
  // a completed backend answer. Live receives the current comparison when it
  // delegates the finished request, avoiding narration of a half-sentence.
  if(b.livePreview){record('live_presentation_delivered',{presentation_id:presentation.id,turn_id:b.turn_id});return;}
  // For an actual requested result, keep perception current during speech;
  // only the invitation to speak waits.
  if(audioPlaying)livePresentationSnapshot(livePresentationFacts);
  const report={b,facts:livePresentationFacts,operation,session:liveConnection};
  b.pendingPresentationReport=true;
  (liveConnection.presentationReports ||= new Map()).set(b.turn_id,report);
  if(!audioPlaying)flushPresentationReports();
 }
 record('live_presentation_delivered',{presentation_id:presentation.id,turn_id:b.turn_id});
}
function flushPresentationReports(){
 const session=liveConnection;
 if(!session?.started||audioPlaying)return;
 for(const [key,{b,facts,operation}] of session.presentationReports||[]){
  // Keep visuals incremental, but speak once after the current edit settles.
  // A second tool call may refine the same sample before the user responds.
  if(reasonRunning&&turn===b)continue;
  session.presentationReports.delete(key);b.pendingPresentationReport=false;
  if(session.editContext?.room_id!==facts.room_id||session.editContext?.content_id!==facts.content_id)continue;
  const delegation=b.liveSession===session?b.liveDelegation||null:null;
  // Descriptions belong to the asset and can predate this edit. They are not
  // a change report. Deliver current result facts independently of that prose.
  livePresentationSnapshot(facts,delegation);
  if(operation)liveAppend('thinking',JSON.stringify({kind:'completed_presentation_operation',name:operation.name}),delegation);
  if(b.pendingPresentationExplanation){liveAppend('thinking',b.pendingPresentationExplanation.text,delegation);b.pendingPresentationExplanation=null;}
  // Speculative visuals may arrive during a pause inside the user's sentence.
  // Update what Live knows without forcing it to take the speaking turn.
  liveAppend(b.livePreview?'thinking':'commentary',JSON.stringify({kind:'presentation_available',id:facts.id,revision:facts.revision,count:facts.items?.length||0,display_ok:facts.display?.ok}),delegation);
 }
}

let liveTaskQueue=Promise.resolve();
// The viewing cursor is independent of the project being edited. Keep a short
// session-relative history so delayed transcripts never acquire a later screen.
function liveObserve(c,session=liveConnection){
 if(!session?.started)return;
 const at=Math.max(0,Date.now()-session.startedAt);
 const view={content_id:c.content_id,room_id:c.room_id,playhead:c.playhead,
  editor_visible:c.editor_visible!==false,selected:c.selected||[],pointer:c.pointer||{},visible_targets:c.visible_targets||[]};
 const rows=session.views||(session.views=[]),last=rows.at(-1);
 if(last&&JSON.stringify(last.view)===JSON.stringify(view))return;
 rows.push({at_ms:at,view:structuredClone(view)});
 while(rows.length>1&&rows[1].at_ms<at-180000)rows.shift();
 if(rows.length>3000)rows.splice(0,rows.length-3000);
}
function liveViewsDuring(session,start,end){
 const rows=session.views||[];
 const prior=rows.findLast(r=>r.at_ms<=start);
 const during=[...(prior?[prior]:[]),...rows.filter(r=>r.at_ms>start&&r.at_ms<=end)];
 // Preserve scene changes and seeks; ordinary playback needs only a sparse trace.
  return during.filter((r,i)=>!i||i===during.length-1||r.view.content_id!==during[i-1].view.content_id||r.view.editor_visible!==during[i-1].view.editor_visible||Math.abs((r.view.playhead||0)-(during[i-1].view.playhead||0))>1||Math.floor(r.at_ms/1000)!==Math.floor(during[i-1].at_ms/1000)).map(r=>{
    const copy=structuredClone(r);
    // Each snapshot already has a timestamp and pointer position. Repeating
    // the whole rolling pointer trail in every snapshot multiplies the input.
    if(copy.view.pointer)delete copy.view.pointer.trail;
    return copy;
  });
}
function liveWorkState(status,detail='',session=liveConnection){
 if(session?.paused&&liveConnection?.started&&session.editContext?.room_id===liveConnection.editContext?.room_id)session=liveConnection;
 if(!session?.started)return;
 session.work={status,detail,at:Date.now()};
 if(session===liveConnection)liveAppend('thinking',JSON.stringify({kind:'execution_state',status,detail,meaning:status==='running'?'依頼の処理中。素材制作や表示の完了を意味しません。':'この依頼の処理状態です。別の制作ジョブの状態とは区別してください。'}));
 liveReplyActivity(session);
 record('live_work_state',{status,detail,observed_at_ms:session.work.at});
}
function liveAppend(kind,content,delegationId=null){
 if(!liveConnection?.started||dc?.readyState!=='open')return;
 // Speculative UI actions have local IDs, not Live API delegation IDs.
 if(delegationId?.startsWith('visual-'))delegationId=null;
 if(kind==='commentary')liveConnection.awaitingSpeechUntil=Date.now()+15000;
 // Each append is limited to 500 tokens. UTF-8 bytes are a conservative bound.
 const parts=[];let part='';
 for(const char of String(content)){if(new TextEncoder().encode(part+char).length>480){parts.push(part);part='';}part+=char;}if(part)parts.push(part);
 // A long result is context followed by ONE invitation to speak. Sending each
 // JSON fragment as commentary made Live repeat the same explanation.
 for(let i=0;i<parts.length;i++){
  const text=parts[i],partKind=kind==='commentary'&&i<parts.length-1?'thinking':kind;
  record('live_append_sent',{kind:partKind,delegation_id:delegationId,text});
  send({type:'session.'+partKind+'.append',event_id:crypto.randomUUID(),delegation_id:delegationId,content:text});
 }
}
function liveTranscript(e,session){
 if(!e.delta)return;
 const role=e.type==='session.input_transcript.delta'?'user':'assistant';
 if(role==='user'){
  session.inputMode='voice';
  if(Number.isFinite(e.end_ms))session.inputTranscriptOffset=Math.min(session.inputTranscriptOffset??Infinity,Date.now()-e.end_ms);
 }
 const prior=session.rows[role];
 let row=prior;
 if(!row||e.start_ms-row.end>1600){
   row={at:new Date().toISOString(),id:'live-'+crypto.randomUUID(),start:e.start_ms,end:e.end_ms,text:'',element:message('',role),memory:{role,text:''}};
   session.rows[role]=row;conversationMemory.push(row.memory);
 }
 row.text+=e.delta;row.end=e.end_ms;row.memory.text=row.text;row.element.textContent=row.text;
 liveReplyActivity(session);
 if(role==='user'){
  row.views=liveViewsDuring(session,row.start,row.end);
  row.memory.observed_views=row.views;
  if(typeof reasonRunning!=='undefined'&&reasonRunning){
    clearTimeout(session.steerTimer);
    const activeTurn=turn;
    session.steerTimer=setTimeout(async()=>{
      if(!reasonRunning||turn!==activeTurn||session.rows.user!==row)return;
      try{
        const result=await api('/steer',{room_id:activeTurn.context.room_id,turn_id:activeTurn.turn_id,name:'steer',args:{text:row.text,item_id:row.id,observed_views:row.views||[]}});
        record('live_context_forwarded',{turn_id:activeTurn.turn_id,item_id:row.id,end_ms:row.end,accepted:result.ok});
      }catch(e){record('live_context_forward_failed',{message:String(e)});}
    },700);
  }
 }
 const queued=audit.findIndex(a=>a.item_id===row.id&&a.source==='gpt-live-1');if(queued>=0)audit.splice(queued,1);
 audit.push({at:row.at,type:role==='user'?'user_transcript':'assistant_transcript',text:row.text,item_id:row.id,source:'gpt-live-1',content_id:session.editContext?.content_id||context?.content_id,observed_views:row.views,start_ms:row.start,end_ms:row.end,session_id:session.id});
 record('live_transcript_delta',{role,delta:e.delta,start_ms:e.start_ms,end_ms:e.end_ms,live_session_id:session.id,event_id:e.event_id});
 if(conversationMemory.length>200)conversationMemory.shift();saveConversation();
 if(role==='assistant'&&activeNotice){activeNotice.transcript=(activeNotice.transcript||'')+e.delta;activeNotice.generated=true;}
 if(role==='user')session.lastVisualTranscriptAt=Date.now();
}

// Visual operations start on a real Live delegation; transcripts only supply context.
function referenceDecisionItems(){
 if(typeof presentationFeed==='undefined')return [];
 const groups=Array.from(presentationFeed.values()).sort((a,b)=>a.at-b.at).slice(-3);
 const identities=new Map();
 return groups.flatMap((p,n)=>p.items.map((i,position)=>{
  const visual=JSON.stringify([i.library_id,i.kind,i.composition,i.scene,i.url,i.asset_id,i.text,i.start,i.end]);
  if(!identities.has(visual))identities.set(visual,i.id);
  return {id:i.id,title:i.title,kind:i.kind,library_id:i.library_id,reference_identity:identities.get(visual),
   url:i.url,source_url:i.source_url,presentation_id:p.id,position:position+1,is_latest:n===groups.length-1};
 }));
}
function consultationMemoKey(session){
 const c=session.editContext||context;
 return 'dan-consultation-v1:'+c?.room_id+':'+c?.content_id;
}
function readConsultationMemo(session){
 try{const memo=JSON.parse(localStorage.getItem(consultationMemoKey(session))||'null');return [2,3].includes(memo?.version)?memo:null;}catch{return null;}
}
// Temporary, read-only instrumentation of the actual consultation state.
// It does not infer answers, send requests, or influence the conversation.
function installConsultationInspector(){
 const nav=document.querySelector('body>header nav');if(!nav)return;
 const style=document.createElement('style');
 style.textContent=`#consultation-inspector{position:fixed;right:16px;top:72px;width:min(360px,calc(100vw - 32px));max-height:calc(100vh - 190px);overflow:auto;z-index:30;background:#191e27f5;border:1px solid #414956;border-radius:16px;padding:18px;box-sizing:border-box;box-shadow:0 12px 40px #0005;color:#e8edf5;font:13px/1.6 system-ui}#consultation-inspector[hidden]{display:none}#consultation-inspector h2{font-size:15px;margin:0 0 4px}#consultation-inspector p{margin:4px 0;color:#a9b5c5}#consultation-inspector dl{margin:12px 0}#consultation-inspector dt{color:#9cacbf;font-size:12px;margin-top:12px}#consultation-inspector dd{margin:3px 0;white-space:pre-wrap;overflow-wrap:anywhere}#consultation-inspector dd[data-known=false]{color:#758093}#consultation-inspector footer{border-top:1px solid #394150;padding-top:10px}#consultation-inspector footer strong{display:block;font-weight:500;color:#b9d6ff}`;
 document.head.append(style);
 const toggle=document.createElement('button');toggle.id='show-consultation';toggle.textContent='相談メモ';toggle.setAttribute('aria-controls','consultation-inspector');nav.prepend(toggle);
 const panel=document.createElement('aside');panel.id='consultation-inspector';panel.setAttribute('aria-label','制作相談メモ・実装確認用');
 const heading=document.createElement('h2');heading.textContent='制作相談メモ';panel.append(heading);
 const note=document.createElement('p');note.textContent='実装確認用 · 会話から整理した内容';panel.append(note);
 const identity=document.createElement('p');panel.append(identity);
 const list=document.createElement('dl');panel.append(list);
 const fields={video_type:'動画の種類',subject:'題材',platform:'公開先',purpose:'作る目的',audience:'想定する視聴者',duration:'尺',materials:'使いたい素材',references:'参考として選んだ作品'};
 const values={};for(const [key,label] of Object.entries(fields)){const dt=document.createElement('dt');dt.textContent=label;const dd=document.createElement('dd');values[key]=dd;list.append(dt,dd);}
 const footer=document.createElement('footer'),next=document.createElement('strong'),pending=document.createElement('p'),updated=document.createElement('p');footer.append(next,pending,updated);panel.append(footer);document.body.append(panel);
 let open=true;try{open=localStorage.getItem('dan-consultation-inspector')!=='closed';}catch{}
 function show(){panel.hidden=!open;toggle.setAttribute('aria-expanded',String(open));}show();
 toggle.onclick=()=>{open=!open;show();toggle.blur();try{localStorage.setItem('dan-consultation-inspector',open?'open':'closed');}catch{}};
 const labels={ask:'必要なことを確認する',compare:'参考を探して見せる',propose:'次の具体化を提案する',conversation:'質問や会話に答える',select:'参考の好みを記録する',reveal:'参考を再表示する',play:'参考を再生する',pause:'参考を一時停止する',listen:'話を聞く',execute:'制作・調査などを実行する'};
 let signature='';
 function render(){
  const current=typeof context==='undefined'?null:context;
  const memo=current?readConsultationMemo({editContext:current}):null;
  const sig=JSON.stringify([current?.room_id,current?.content_id,memo]);if(sig===signature)return;signature=sig;
  identity.textContent=current?.content_id?'対象：'+current.content_id.slice(0,8):'制作相談の開始待ち';
  let count=0;for(const key of Object.keys(fields)){const item=memo?.version===3?memo.fields?.[key]:null;const known=item&&item.status!=='unknown';if(known)count++;
   values[key].textContent=known?(item.status==='undecided'?'未定で進める：':'')+item.value:'未確認';values[key].dataset.known=String(!!known);}
  next.textContent=memo?.ready_for_draft?'下書きへ進む相談ができます':`確認済み ${count} / 8`;
  pending.textContent=memo?.reference_agreed?'参考の方向：合意済み':'参考の方向：まだ合意していません';
  updated.textContent=memo?.version===2?'旧形式の記録は引き継がず、会話の内容から整理し直します。':'未確認と、相談の結果「未定で進める」は区別します。';
 }
 render();const timer=setInterval(render,500);window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});
}
if(typeof document!=='undefined')document.addEventListener?.('DOMContentLoaded',installConsultationInspector,{once:true});

async function executeLiveConsultationTool(item,session,captured){
 const args=JSON.parse(item.arguments||'{}');
 const owner={editContext:captured};
 const sheet=()=>{const memo=readConsultationMemo(owner);return memo?.version===3?memo:null;};
 if(item.name==='get_consultation_state')return {context:captured, sheet:sheet(),
  displayed:context?.room_id===captured.room_id&&context?.content_id===captured.content_id?referenceDecisionItems():[],production:liveFacts().production};
 if(item.name==='update_consultation_sheet'){
  const updated=await api('/consultation/update',{previous:sheet(),changes:args.changes,reference_agreed:args.reference_agreed});
  localStorage.setItem(consultationMemoKey(owner),JSON.stringify(updated));
  record('consultation_sheet_updated',{room_id:captured.room_id,content_id:captured.content_id,sheet:updated,source:'live_responses_tool'});
  liveAppend('thinking',JSON.stringify({kind:'consultation_sheet',sheet:updated,read_silently:true}));
  return {saved:true,sheet:updated};
 }
 if(item.name==='search_reference_library'){
  const current=()=>context?.room_id===captured.room_id&&context?.content_id===captured.content_id;
  liveWorkState('running','参考を探しています',session);
  try{
   const result=await api('/live/reference-search',{...args,dialogue:conversationMemory.slice(-40),items:current()?referenceDecisionItems():[]});
   if(!result.available||!result.ids?.length)return {shown:false,...result};
   if(!current())return {shown:false,reason:'view_changed',ids:result.ids};
   const shown=await api('/reference-library/present',{room_id:captured.room_id,content_id:captured.content_id,ids:result.ids,comparison_key:session.id+':'+item.call_id});
   if(!current())return {shown:false,reason:'view_changed'};
   renderReferences(shown.presentation);const display=await presentationReady(shown.presentation);
   record('live_reference_tool_displayed',{room_id:captured.room_id,content_id:captured.content_id,ids:result.ids,...display});
   return {shown:display.ok,items:shown.presentation.items.map(livePresentationItem),search_ms:result.elapsed_ms};
  }finally{liveWorkState('idle','',session);}
 }
 if(item.name==='control_reference'){
  const ok=await livePresentationAction({...captured,live_dialogue:conversationMemory},session,null,
   ()=>context?.room_id===captured.room_id&&context?.content_id===captured.content_id,
   {handled:true,action:args.action,item_id:args.item_id,destination:'viewer'});
  return {ok};
 }
 if(item.name==='run_editor_task'){
  if(!args.task?.trim())throw Error('制作依頼が空です');
  if(reasonRunning)return {accepted:false,reason:'work_in_progress',production:liveFacts().production};
  const c={...captured,consultation_memo:sheet(),live_dialogue:conversationMemory.slice(-200),live_facts:liveFacts()};
  const b=await begin(c,'voice',args.task,epoch);if(!b)return {accepted:false};
  b.liveSession=session;b.liveDelegation=null;
  runReasoning().catch(error);
  return {accepted:true,turn_id:b.turn_id,completed:false};
 }
 throw Error('Unknown conversation tool: '+item.name);
}

async function handleLiveResponseEvent(envelope,session){
 const e=envelope.event||{},key=envelope.delegation_id||e.response?.id||'current';
 session.responseTools||=new Map();session.responseContexts||=new Map();
 if(e.type==='response.created')session.responsePending=true;
 if(!session.responseContexts.has(key))session.responseContexts.set(key,structuredClone(session.editContext||context));
 if(e.type==='response.output_item.done'&&e.item?.type==='function_call'){
  const calls=session.responseTools.get(key)||[];
  if(calls.some(c=>c.call_id===e.item.call_id))return;
  calls.push(e.item);session.responseTools.set(key,calls);return;
 }
 if(['response.failed','response.incomplete','error'].includes(e.type)){
  session.responsePending=false;
  session.responseTools.delete(key);session.responseContexts.delete(key);
  record('live_response_failed',{type:e.type,error:e.error||e.response?.error});return;
 }
 if(e.type!=='response.completed')return;
 const calls=session.responseTools.get(key)||[];session.responseTools.delete(key);
 const captured=session.responseContexts.get(key);session.responseContexts.delete(key);
 if(!calls.length){session.responsePending=false;return;}
 // Keep dependent sheet writes in order and return every call before resuming.
 session.toolQueue=(session.toolQueue||Promise.resolve()).then(async()=>{
  const outputs=[];
  for(const item of calls){let output;try{output=await executeLiveConsultationTool(item,session,captured);}catch(exc){output={error:String(exc)};}
   outputs.push({type:'function_call_output',call_id:item.call_id,output:JSON.stringify(output)});
   record('live_consultation_tool_done',{name:item.name,call_id:item.call_id,error:output.error||null});}
  if(liveConnection!==session||!session.started)return;
  for(const output of outputs)send({type:'response.item.create',event_id:crypto.randomUUID(),item:output});
  send({type:'response.create',event_id:crypto.randomUUID()});
 }).catch(error);
 await session.toolQueue;
}
function visualDecision(session,dialogue,items){
 // Jev reads words and candidate identities, not the execution view trace.
 // Preview and delegation must share a decision when those inputs agree.
 // The response currently being spoken is not a new user preference. Freeze
 // the request at the latest user turn so speculation and delegation share
 // one result even while Live is streaming its acknowledgement.
 const lastUser=dialogue.findLastIndex(r=>r.role==='user');
 const words=dialogue.slice(0,lastUser+1).map(r=>({role:r.role,text:r.text}));
 const focus=typeof referenceFocus==='undefined'?null:referenceFocus;
 const pending=session.pendingReference;
 const pendingReference=pending&&pending.room===session.editContext?.room_id&&pending.content===session.editContext?.content_id?
   {text:pending.text,ids:pending.ids}:null;
 const executionState=liveFacts().production;
 const consultationMemo=readConsultationMemo(session);
 const key=JSON.stringify({utterance:session.rows.user?.id||crypto.randomUUID(),dialogue:words,items,focus,pendingReference,active:executionState?.active});
 if(session.visualDecision?.key===key)return session.visualDecision.promise;
 const decisionId=crypto.randomUUID(),decisionContext={room_id:session.editContext?.room_id,content_id:session.editContext?.content_id};
 record('visual_decision_started',{decision_id:decisionId,input_id:session.rows.user?.id,input_text:session.rows.user?.text,
  ...decisionContext});
 const memoKey=consultationMemoKey(session);
 const promise=api('/visual-decision',{dialogue:words,items,focus,pending_reference:pendingReference,execution_state:executionState,consultation_memo:consultationMemo}).then(result=>{
  // Preserve retrieved references across transcript boundaries. Only the
  // semantic disposition of newer user words may reuse or discard them.
  if(session.visualDecision?.key===key){
   if(result.available&&result.consultation_memo){
    try{localStorage.setItem(memoKey,JSON.stringify(result.consultation_memo));}catch{}
    record('consultation_memo_updated',{...decisionContext,memo:result.consultation_memo});
   }
   if(['revise','discard'].includes(result.pending_disposition))session.pendingReference=null;
   if(result.action==='compare'&&result.selected_library_ids?.length)
    session.pendingReference={room:decisionContext.room_id,content:decisionContext.content_id,
      text:words.filter(r=>r.role==='user').map(r=>r.text).join('\n'),ids:result.selected_library_ids};
  }
  record('visual_decision_finished',{decision_id:decisionId,action:result.action,available:result.available,
   selected_library_ids:result.selected_library_ids,elapsed_ms:result.elapsed_ms,failure:result.failure,
   discovery:result.discovery?{change:result.discovery.change,next:result.discovery.next_axis,
     preferences:Object.fromEntries(Object.entries(result.discovery.beliefs||{}).map(([k,v])=>[k,{preferred:v.preferred,avoid:v.avoid}])),
     comparison:result.discovery.comparison?.reason,reused_ids:result.discovery.reused_ids}:null,
   retrieval:result.url_retrieval?{available:result.url_retrieval.available,elapsed_ms:result.url_retrieval.elapsed_ms,failure:result.url_retrieval.failure}:null,
   verification:result.verification?{source:result.verification.source,elapsed_ms:result.verification.elapsed_ms,available:result.verification.available}:null,
   ...decisionContext});
  return result;
 }).catch(e=>{record('visual_decision_failed',{decision_id:decisionId,message:String(e)});throw e;});
 session.visualDecision={key,promise};return promise;
}
async function livePresentationAction(captured,session,id,isCurrent,decision=null){
 if(typeof presentationFeed==='undefined'||!presentationFeed.size)return false;
 const items=Array.from(presentationFeed.values()).sort((a,b)=>a.at-b.at).flatMap(p=>p.items.map(i=>({id:i.id,title:i.title,kind:i.kind,group:p.id}))).slice(-60);
 if(!items.length)return false;
 const inputId=session.rows.user?.id,inputText=session.rows.user?.text;
 let result;
 try{result=decision||await api('/presentation-action',{dialogue:captured.live_dialogue.slice(-40),items,focus:typeof referenceFocus==='undefined'?null:referenceFocus});}
 catch(e){record('jev_fallback',{reason:'request_failed'});return false;}
 record('jev_decision',result);
 if(!isCurrent()||context.room_id!==captured.room_id||context.content_id!==captured.content_id||session.rows.user?.id!==inputId||session.rows.user?.text!==inputText)return false;
 if(!result.handled||!['reveal','play','pause'].includes(result.action)||!items.some(i=>i.id===result.item_id))return false;
 const card=$('reference-cards').querySelector('[data-item-id="'+CSS.escape(result.item_id)+'"]');
 if(!card)return false;
 const player=card.querySelector('.proposal-player')||document.querySelector?.('[data-proposal-item-id="'+CSS.escape(result.item_id)+'"]');
 if(result.action!=='reveal'&&!player?.control)return false;
 document.body.classList.add('has-references');
 card.scrollIntoView({block:'center'});
 if(result.action!=='reveal'){
  try{if(!await player.control(result.action))return false;}catch(e){record('jev_action_failed',{action:result.action});return false;}
 }
 if(result.destination==='viewer'&&!player?.closest?.('dialog'))player?.querySelector('.proposal-zoom')?.click();
 record('jev_action_applied',{action:result.action,item_id:result.item_id});
 liveAppend('commentary',JSON.stringify({kind:'presentation_action_completed',action:result.action,item:items.find(i=>i.id===result.item_id)}),id);
 return true;
}
async function liveDelegate(event,session){
 const delegationStarted=performance.now();
 const id=event.delegation.id;
 sendExecutionFacts(session);
 if(liveCalls.has(id))return;liveCalls.add(id);
 const captured=structuredClone(session.editContext||context);
 captured.live_facts=liveFacts();
 captured.consultation_memo=readConsultationMemo(session);
 captured.live_dialogue=conversationMemory.slice(-200).map(r=>({role:r.role,text:r.text,observed_views:r.observed_views||[]}));
 const utterance=session.rows.user;
 if(session.visualSelected&&utterance?.id&&session.visualSelected.id===utterance.id&&session.visualSelected.text===utterance.text){
   liveAppend('thinking',JSON.stringify({kind:'reference_selected',item_id:session.visualSelected.itemId,saved:true,production_started:false}),id);return;
 }
 if(session.visualPresented&&session.visualPresented.id===utterance?.id&&session.visualPresented.text===utterance?.text){
   queueReferenceReport({liveDelegation:id},livePresentationFacts,session);return;
 }
 captured.observed_views=utterance?.views||[];
 const spokenView=captured.observed_views[0]?.view;
 if(spokenView?.content_id===captured.content_id)Object.assign(captured,structuredClone(spokenView));
 captured.viewed_context=structuredClone(context);
 // A continuing utterance updates the running agent instead of throwing away
 // its search/results and starting another cold turn. Explicit cancellation
 // remains a decision for the agent receiving the original words.
 if(typeof reasonRunning!=='undefined'&&reasonRunning&&turn?.liveSession===session&&utterance?.text){
   const current=turn;
   try{
     const result=await api('/steer',{room_id:current.context.room_id,turn_id:current.turn_id,name:'steer',args:{text:utterance.text,item_id:utterance.id,observed_views:utterance.views||[]}});
     if(result.ok){
       current.liveDelegation=id;
       record('live_delegation_forwarded',{delegation_id:id,turn_id:current.turn_id,item_id:utterance.id});
       return;
     }
   }catch(e){record('live_context_forward_failed',{message:String(e)});}
 }
 const revision=session.delegationRevision=(session.delegationRevision||0)+1;
 if(typeof reasonRunning!=='undefined'&&reasonRunning){
   const old=turn;
   epoch++;reasonController?.abort();reasonController=null;reasonRunning=false;
   session.canceling=cancelTurn(old);
   record('live_reasoning_superseded',{delegation_id:id,previous_turn:old?.turn_id});
 }
 liveTaskQueue=liveTaskQueue.then(async()=>{
   if(revision!==session.delegationRevision)return;
   if((liveConnection!==session||!session.started)&&!session.paused)return;
   if(context?.room_id!==captured.room_id)return;
   if(session.canceling){await session.canceling;session.canceling=null;}
   if(revision!==session.delegationRevision)return;
   liveWorkState('running','依頼に合う参考と操作を調べています',session);
   setBusy(true);
   if(revision!==session.delegationRevision||((liveConnection!==session||!session.started)&&!session.paused))return;
   const sampleStart=delegationStarted,inputId=session.rows.user?.id;
   let inputText=session.rows.user?.text;
   const referenceCurrent=()=>revision===session.delegationRevision&&session.rows.user?.id===inputId&&session.rows.user?.text===inputText&&context?.room_id===captured.room_id&&((liveConnection===session&&session.started)||session.paused);
   const sameInput=()=>revision===session.delegationRevision&&session.rows.user?.id===inputId&&context?.room_id===captured.room_id&&((liveConnection===session&&session.started)||session.paused);
   const waitQuiet=async()=>{
     while(sameInput()&&(Date.now()-(session.lastVisualTranscriptAt||0)<350||Date.now()-(session.lastInputSound||0)<350))await new Promise(resolve=>setTimeout(resolve,100));
   };
   await waitQuiet();if(!sameInput()){setBusy(false);return;}
   inputText=session.rows.user?.text;
   captured.live_dialogue=conversationMemory.slice(-200).map(r=>({role:r.role,text:r.text,observed_views:r.observed_views||[]}));
   let library;
   try{const recent=referenceDecisionItems();library=await visualDecision(session,captured.live_dialogue.slice(-40),recent);record('visual_decision',{input_id:inputId,input_text:inputText,action:library?.action,destination:library?.destination,elapsed_ms:library?.elapsed_ms,selected_library_ids:library?.selected_library_ids,coverage_missing:library?.coverage_missing,action_probabilities:library?.answers?.action?.probabilities,target_confidence:library?.answers?.target?.confidence});}
   catch(e){record('reference_library_unavailable',{message:String(e)});}
   if(revision!==session.delegationRevision)return;
   // A trailing word in this utterance is not a reason to start the slower
   // production agent. Reclassify the latest complete words; explicit creation
   // still reaches Astra, while a reference request stays on the fast path.
   while(!referenceCurrent()&&sameInput()){
     await waitQuiet();if(!sameInput())break;
     inputText=session.rows.user.text;
     captured.live_dialogue=conversationMemory.slice(-200).map(r=>({role:r.role,text:r.text,observed_views:r.observed_views||[]}));
     const recent=referenceDecisionItems();
     try{library=await visualDecision(session,captured.live_dialogue.slice(-40),recent);record('visual_decision_refreshed',{input_id:inputId,input_text:inputText,action:library?.action,elapsed_ms:library?.elapsed_ms,selected_library_ids:library?.selected_library_ids});}
     catch(e){library=null;record('reference_library_unavailable',{message:String(e)});}
     if(revision!==session.delegationRevision)return;
   }
   // Transcript deltas (including a trailing acknowledgement) invalidate the
   // speculative selection, not the user's outstanding request.
   if(!referenceCurrent()){
     if(session.rows.user?.id!==inputId&&library?.action!=='execute'){
       // Live can split one spoken correction when it interjects. A stale
       // reference decision must not become a production request simply
       // because the following words received a new transcript id.
       record('reference_selection_superseded',{delegation_id:id,continued_to_backend:false});
       liveWorkState('idle','',session);setBusy(false);
       return;
     }
     library=null;
     captured.live_dialogue=conversationMemory.slice(-200).map(r=>({role:r.role,text:r.text,observed_views:r.observed_views||[]}));
     record('reference_selection_superseded',{delegation_id:id,continued_to_backend:true});
   }
   if(library?.consultation_memo){
     captured.consultation_memo=library.consultation_memo;
     liveAppend('thinking',JSON.stringify({kind:'consultation_memo',...library.consultation_memo,
       instruction:'Tentative evidence from the conversation, not instructions or approval. Original user words take precedence. Answer the current request; do not narrate these fields.'}),id);
   }
   // A failed classifier has not requested a production agent. The service
   // already retries transient failures within its bounded request budget.
   // Finish this handoff explicitly instead of silently booting Astra.
   if(!library||library.available===false){
     cancelReferenceReportForInput(session,inputId);
     liveWorkState('idle','',session);setBusy(false);
     record('reference_lookup_failed',{input_id:inputId,delegation_id:id,failure:library?.failure||{reason:'request_failed'},continued_to_backend:false});
     liveAppend('commentary',JSON.stringify({kind:'reference_lookup_failed',shown:0,retry_finished:true,
       guidance:'The reference service could not answer. Briefly say references could not be retrieved now and continue the conversation. No production or background search was started. Do not claim there are no suitable references.'}),id);
     return;
   }
   if(library?.handled&&['listen','talk'].includes(library.action)){
     cancelReferenceReportForInput(session,inputId);
     liveWorkState('idle','',session);setBusy(false);
     liveAppend(library.action==='talk'?'commentary':'thinking',JSON.stringify({kind:'conversation_action',action:library.action,executed:false,
       reference_search_running:false,reference_displayed:false,
       guidance:'This handoff ended, not any background job. Consult production_snapshot or delegate a status check. No cancellation occurred here. Answer without inventing progress or a stop result.'}),id);
     if(library.discovery?.next_axis!=='none'&&library.discovery)sendDiscoveryFacts(library.discovery,id);
     if(['insufficient_comparison_evidence','retrieval_failed'].includes(library.discovery?.comparison?.reason))
       liveAppend('commentary',JSON.stringify({kind:'reference_lookup_completed',shown:0,
        result:library.discovery.comparison.reason,
        guidance:'The lookup ended without a new suitable reference. Do not say you are still searching or have displayed one. Briefly explain and offer a useful next step from the user conversation.'}),id);
     return;
   }
   if(library?.handled&&['reveal','play','pause'].includes(library.action)&&await livePresentationAction(captured,session,id,referenceCurrent,library)){
     liveWorkState('idle','',session);setBusy(false);return;
   }
   if(library?.handled&&library.selected_library_ids?.length){
     const previous=livePresentationFacts;
     const same=previous?.room_id===captured.room_id&&previous?.content_id===captured.content_id&&
       JSON.stringify((previous.items||[]).map(i=>i.library_id).sort())===JSON.stringify([...library.selected_library_ids].sort());
     if(same){
       session.pendingReference=null;
       sendReferenceFacts(previous,id);
       liveAppend('thinking',JSON.stringify({kind:'reference_comparison_unchanged',new_items:0,
         instruction:'The same references remain visible. Do not describe them as new or different. Respect an already chosen direction; ask only about unresolved preferences.'}),id);
       record('reference_library_reused',{presentation_id:previous.id,selected_library_ids:library.selected_library_ids});
       liveWorkState('idle','',session);setBusy(false);return;
     }
     // Showing an existing reference is not an editing transaction. Avoid the
     // timeline snapshot and production-context assembly in /begin entirely.
     const b={context:captured,turn_id:'reference-'+crypto.randomUUID(),liveDelegation:id,
       liveSession:session,livePreview:false,inputId,discovery:library.discovery,referenceOperation:'selected_existing_library_examples_without_modification'};
     const shown=await api('/reference-library/present',{room_id:captured.room_id,content_id:captured.content_id,
       ids:library.selected_library_ids,comparison_key:session.id+':'+inputId});
     if(shown.presentation&&referenceCurrent()){
       renderReferences(shown.presentation);const display=await presentationReady(shown.presentation);
       // Further words cannot undo the fact that this visual has appeared.
       // Keep the acknowledgement silent if the speaker is still refining it.
       if(revision===session.delegationRevision&&session.rows.user?.id===inputId&&context?.room_id===captured.room_id){
         session.pendingReference=null;
         record('reference_library_displayed',{input_id:inputId,room_id:captured.room_id,content_id:captured.content_id,input_sound_at_ms:session.lastInputSound||null,delegation_to_paint_ms:Math.round(performance.now()-sampleStart),ranking_ms:library.elapsed_ms,selection_backend:'jev',selected_library_ids:library.selected_library_ids,presentation_id:shown.presentation.id,count:shown.presentation.items.length,...display});
         if(display.ok){const memo=readConsultationMemo(session);if(memo){memo.pending_request=null;try{localStorage.setItem(consultationMemoKey(session),JSON.stringify(memo));}catch{}}}
         session.visualPresented={id:inputId,text:inputText,libraryIds:JSON.stringify(library.selected_library_ids)};
         if(!referenceCurrent())b.livePreview=true;
         livePresented(b,shown.presentation,display);
       }
     }
     liveWorkState('idle','',session);setBusy(false);
     return;
   }
   if((library?.reference_confidence||0)>=.6)captured.reference_library=library;
   if(library?.handled&&library.action==='select'){
     const chosen=await api('/choose',{room_id:captured.room_id,content_id:captured.content_id,
       item_id:library.item_id,feedback:inputText||''});
     const saved=chosen.ok!==false;
     if(saved)session.visualSelected={id:inputId,text:inputText,itemId:library.item_id};
     record('reference_selected',{input_id:inputId,item_id:library.item_id,saved,elapsed_ms:Math.round(performance.now()-delegationStarted)});
     const selectedItem=Array.from(presentationFeed.values()).flatMap(p=>p.items).find(i=>i.id===library.item_id);
     const selectionFact={kind:'reference_selected',item_id:library.item_id,saved,title:selectedItem?.title||''};
     while(new TextEncoder().encode(JSON.stringify(selectionFact)).length>460&&selectionFact.title.length)selectionFact.title=selectionFact.title.slice(0,-1);
     liveAppend('thinking',JSON.stringify(selectionFact),id);
     liveAppend('thinking',JSON.stringify({kind:'creative_next_step',next:library.consultation_memo?.guidance||'Retain the chosen overall direction. Proactively propose the next useful artifact when sufficient; do not force compatible scene elements into an either-or choice.'}),id);
     liveWorkState('idle','',session);setBusy(false);return;
   }
   const b=await begin(captured,'voice','',epoch);if(!b)return;
   if(revision!==session.delegationRevision)return;
   b.liveDelegation=id;b.liveSession=session;b.livePreview=!!event.visualPreview;b.inputId=inputId;
   if(event.visualPreview){liveWorkState('idle','',session);setBusy(false);return;}
   record('live_backend_started',{delegation_id:id,input_id:inputId,turn_id:b.turn_id,room_id:captured.room_id,content_id:captured.content_id,model:'gpt-6-astra',backend:'codex_cli',billing:'chatgpt_plan'});
   liveWorkState('running','',session);
   try{await runReasoning();if(revision===session.delegationRevision)liveWorkState(waitingForUser?'waiting':'idle',waitingForUser?'処理は実行していません。ユーザーの続きの発言を待っています。':'今回の応答は終了。進行中の制作があれば別の実行記録に表示されます。',session);}
   catch(e){if(revision!==session.delegationRevision||e.name==='AbortError')return;throw e;}
 }).catch(e=>{record('live_tool_error',{message:String(e)});liveWorkState('failed',String(e),session);setBusy(false);error(e);liveAppend('commentary','制作担当の処理が止まりました。'+e.message,id);});
}
async function connectLive(){
 if(liveClosing)await liveClosing;
 if(liveConnection?.started&&dc?.readyState==='open')return;
 if(connecting)return connecting;
 const gen=generation;
 connecting=(async()=>{
  state('LIVE 1に接続しています…');
  const session={started:false,rows:{},id:null,closing:false};liveConnection=session;liveCalls.clear();
  const peer=new RTCPeerConnection();pc=peer;const playback=new Audio();audio=playback;playback.autoplay=true;
  peer.addTransceiver('audio',{direction:'sendrecv'});
  const channel=peer.createDataChannel('oai-events');dc=channel;
  let ready,fail;const opened=new Promise((resolve,reject)=>{ready=resolve;fail=reject;});opened.catch(()=>{});
  peer.ontrack=e=>{
    playback.srcObject=new MediaStream([e.track]);playback.play().catch(()=>{});
    const ac=new AudioContext();session.audioContext=ac;const source=ac.createMediaStreamSource(playback.srcObject),analyser=ac.createAnalyser();analyser.fftSize=256;source.connect(analyser);ac.resume().catch(()=>{});
    const samples=new Float32Array(analyser.fftSize);let lastSound=0,inputTrack=null,inputSource=null;
    const inputAnalyser=ac.createAnalyser();inputAnalyser.fftSize=1024;
    const inputSamples=new Float32Array(inputAnalyser.fftSize);
    session.meter=setInterval(()=>{
      if(liveConnection!==session)return;
      // This meter only gates speculative UI updates. Live still owns voice
      // turn-taking. Observe the actual sender, including microphone changes.
      const track=peer.getSenders().find(s=>s.track?.kind==='audio')?.track;
      if(track!==inputTrack){inputSource?.disconnect();inputSource=null;inputTrack=track;
        if(track){inputSource=ac.createMediaStreamSource(new MediaStream([track]));inputSource.connect(inputAnalyser);}}
      if(inputTrack?.enabled){inputAnalyser.getFloatTimeDomainData(inputSamples);
        if(Math.sqrt(inputSamples.reduce((sum,x)=>sum+x*x,0)/inputSamples.length)>.01)session.lastInputSound=Date.now();}
      analyser.getFloatTimeDomainData(samples);const rms=Math.sqrt(samples.reduce((sum,x)=>sum+x*x,0)/samples.length);
      if(rms>.004&&!playback.paused){lastSound=Date.now();session.quietSince=lastSound;session.awaitingSpeechUntil=0;if(!audioPlaying)record('voice_output_started',{live_session_id:session.id});audioPlaying=true;if(activeNotice)activeNotice.audioStarted=true;}
      else if(audioPlaying&&Date.now()-lastSound>900){audioPlaying=false;liveReplyActivity(session);record('voice_output_stopped',{live_session_id:session.id});flushPresentationReports();if(activeNotice){activeNotice.audioEnded=true;finishNotice();}}
    },100);
  };
  channel.onmessage=({data})=>{
    const e=JSON.parse(data);
    if(e.type==='session.closed'){session.finalized=true;record('live_session_closed',{reason:e.reason,usage:e.usage});flushAudit().catch(()=>{});session.finalize?.();if(!session.closing&&gen===generation)recoverConnection('live_'+e.reason).catch(error);return;}
    if(gen!==generation||liveConnection!==session)return;
    if(e.type==='session.started'){session.started=true;session.id=e.session.id;connectedAt=Date.now();session.startedAt=connectedAt;session.editContext=structuredClone(livePausedContext?.room_id===context?.room_id?livePausedContext:context);livePausedContext=null;session.views=[];liveObserve(context,session);const memo=readConsultationMemo(session);if(memo)liveAppend('thinking',JSON.stringify({kind:'consultation_memo',...memo,instruction:'Resume this consultation without asking established facts again. Read silently.'}));record('connection_stage',{stage:'ready',model:'gpt-live-1',live_session_id:session.id});state('接続しました');ready();return;}
    if(['session.input_transcript.delta','session.output_transcript.delta'].includes(e.type)){liveTranscript(e,session);return;}
    if(['session.commentary.appended','session.thinking.appended','session.instructions.appended'].includes(e.type)){record('live_append_ack',{kind:e.type,client_event_id:e.client_event_id});return;}
    if(e.type==='response.event'){handleLiveResponseEvent(e,session).catch(error);return;}
    if(e.type==='session.delegation.created'){record('live_delegation',{delegation:e.delegation});if(e.delegation.target==='responses'){session.responsePending=true;session.responseContexts||=new Map();session.responseContexts.set(e.delegation.id,structuredClone(session.editContext||context));return;}liveDelegate(e,session);return;}
    if(e.type==='error'){record('live_error',{error:e.error});error(Error(e.error?.message||'LIVE 1の処理でエラーが発生しました'));return;}
    if(e.type==='session.usage.updated')record('live_usage',{usage:e.usage});
  };
  channel.onclose=()=>{fail(Error('LIVE 1への接続が閉じられました'));if(!session.closing&&gen===generation)recoverConnection('live_channel_closed').catch(error);};
  peer.onconnectionstatechange=()=>{if(peer.connectionState==='failed'&&!session.closing&&gen===generation)recoverConnection('live_connection_failed').catch(error);};
  const offer=await peer.createOffer();await peer.setLocalDescription(offer);
  if(peer.iceGatheringState!=='complete')await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{peer.removeEventListener('icegatheringstatechange',check);reject(Error('音声接続の準備がタイムアウトしました'));},10000);function check(){if(peer.iceGatheringState==='complete'){clearTimeout(timer);peer.removeEventListener('icegatheringstatechange',check);resolve();}}peer.addEventListener('icegatheringstatechange',check);check();});
  const result=await api('/live/session',{sdp:peer.localDescription.sdp,history:conversationMemory,client_build:window.__danEditorBuild||null});
  record('live_runtime',{...result.runtime,model:result.model});
  if(gen!==generation)return;
  session.id=result.session.id;await peer.setRemoteDescription({type:'answer',sdp:result.transport.sdp});
  let timer;try{await Promise.race([opened,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('LIVE 1への接続がタイムアウトしました')),30000);})]);}finally{clearTimeout(timer);}
 })();
 try{await connecting;}catch(e){disconnect('live_connect_error',true);throw e;}finally{connecting=null;}
}
function closeLiveTransport(){
 const session=liveConnection;if(!session)return;liveConnection=null;session.closing=true;session.started=false;
 const channel=dc,peer=pc,playback=audio,stream=mic;dc=null;pc=null;audio=null;mic=null;
 stream?.getTracks().forEach(t=>t.enabled=false);clearInterval(session.meter);
 let finish;liveClosing=new Promise(resolve=>{finish=resolve;});
 playback?.pause();
 const cleanup=()=>{clearTimeout(session.closeTimer);stream?.getTracks().forEach(t=>t.stop());channel?.close();peer?.close();playback?.pause();if(playback)playback.srcObject=null;session.audioContext?.close().catch(()=>{});liveClosing=null;finish();};
 session.finalize=cleanup;
 if(channel?.readyState==='open'){channel.send(JSON.stringify({type:'session.close'}));session.closeTimer=setTimeout(()=>{record('live_close_unconfirmed',{live_session_id:session.id});cleanup();},10000);}else cleanup();
}
async function announceLiveCompletion(){
 finishMutedLive();
 await liveAutoDisconnect();
 if(activeNotice?.liveSentAt&&Date.now()-activeNotice.liveSentAt>45000&&!audioPlaying){
   record('live_notification_unconfirmed',{job_id:activeNotice.job_id});completionNotices.unshift(activeNotice);activeNotice=null;noticeRetryAt=Date.now()+15000;saveConversation();
 }
 if(Date.now()<noticeRetryAt)return;
 // Only a paused conversation may call the user back. Closing voice mode or
 // disabling notifications cancels that permission for this UI session.
 if(!micOn&&livePausedContext&&!notificationsPaused&&!liveAutoConnecting&&!busy){
   const available=completionNotices.some(n=>n.room_id===livePausedContext.room_id&&n.content_id===livePausedContext.content_id&&(n.kind!=='question'||n.question_id===pendingQuestion?.id))||liveDeferredReports.some(r=>r.room_id===livePausedContext.room_id&&r.content_id===livePausedContext.content_id);
   if(available){
     liveAutoConnecting=true;
     try{
       await toggleMic();
       if(liveConnection?.started&&micOn){
         liveConnection.automaticReport=true;liveConnection.idleSince=null;
         endTone(true);document.body.classList.add('incoming-call');setTimeout(()=>document.body.classList.remove('incoming-call'),3000);
         record('live_auto_connected',{microphone_on:true});
       }else noticeRetryAt=Date.now()+15000;
     }catch(e){error(e);noticeRetryAt=Date.now()+15000;}
     finally{liveAutoConnecting=false;}
   }
 }
 if(!completionNotices.length||activeNotice||!liveConnection?.started||!micOn||notificationsPaused||busy||audioPlaying)return;
 const owner=liveEditingContext();
 const noticeIndex=completionNotices.findIndex(n=>n.room_id===owner?.room_id&&n.content_id===owner?.content_id);
 if(noticeIndex<0)return;
 const [notice]=completionNotices.splice(noticeIndex,1);
 if(notice.kind==='question'&&notice.question_id!==pendingQuestion?.id)return;
 activeNotice={...notice,generated:false,audioStarted:false,audioEnded:false,liveSentAt:Date.now()};
 const facts=notice.kind==='question'?{question:notice.question?.text}:{status:notice.status,timeline:notice.current_timeline,result:notice.final_result,report:notice.production_report_before_save,error:notice.error};
 liveAppend('commentary','制作担当から新しい結果です。今の会話に合わせて伝えてください。'+JSON.stringify(facts));
 record('live_notification_sent',{job_id:notice.job_id});
}

async function submitLiveText(text){
 $('input').value='';message(text,'user');record('user_transcript',{text,input_mode:'text'});
 if(micOn)await connectLive();const session=liveConnection,captured=structuredClone(context);
 liveTaskQueue=liveTaskQueue.then(async()=>{
   if(liveConnection!==session)return;
   await flushAudit();const b=await begin(captured,'text',text,epoch);if(!b)return;
   b.liveSession=session;b.liveText=true;liveAppend('thinking','ユーザーからのテキスト: '+text);
   await runReasoning();
 }).catch(error);
}
