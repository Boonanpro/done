'use strict';
const $ = id => document.getElementById(id), base = '/api/v1/editor-assistant';
let context=null, pc=null, dc=null, mic=null, audio=null, turn=null, connecting=null;
let busy=false, micOn=false, generation=0, epoch=0, answer=null, active=false;
let reasonController=null,reasonRunning=false,relayActive=false;
const relayQueue=[],relayResponses=new Set();
let targetTurn=null, previousTurn=null, pendingNewId=null, speech=null, queue=Promise.resolve();
const responses=new Map(), jobs=new Map(), acknowledgments=new Map();
const spokenJobs=new Set();
const audioTurns=new Map(), pendingTranscripts=new Map();
const speechItems=new Map();
const transcriptWaiters=new Map(), completionNotices=[];
let audioPlaying=false;
let pendingQuestion=null,activeNotice=null,noticeRetryAt=0;
let lastNoticeBlock='';
let notificationsPaused=false,waitingForUser=false;
const seenQuestions=new Set();
async function answerCurrentQuestion(text,questionId){
  const q=pendingQuestion;if(!q)return false;
  if(q.id!==questionId)throw Error('質問が更新されています。現在の質問を確認してください。');
  const result=await api('/answer',{room_id:context.room_id,content_id:context.content_id,job_id:q.job_id,question_id:q.id,text});
  record('question_answered',{job_id:q.job_id,question_id:q.id,text});
  pendingQuestion=null;message(result.delivery==='saved'?'回答を保存しました。':'回答を送りました。');return result;
}
const auditSession=crypto.randomUUID(), audit=[];
let contextItems=[],pictureItems=[],retryTimer=null,retryCount=0;
let renewing=false,connectedAt=0;
const conversationMemory=[];
let recoveryId=0;
function saveConversation(){
  if(!context?.room_id)return;
  try{localStorage.setItem('editor-conversation:'+context.room_id,JSON.stringify({notificationPolicy:2,trackedJobs:[...jobs.keys()],notices:activeNotice?[activeNotice,...completionNotices]:completionNotices,messages:conversationMemory,content_id:context.content_id,previousTurn,notificationsPaused,waitingForUser}));}catch(e){recordStorageFailure(e);}
}
function recordStorageFailure(e){audit.push({at:new Date().toISOString(),type:'history_storage_error',message:String(e)});}
function restoreConversation(room){
  try{
    const saved=JSON.parse(localStorage.getItem('editor-conversation:'+room)||'null');
    if(saved){conversationMemory.push(...(saved.messages||[]).slice(-200));notificationsPaused=saved.notificationPolicy===2&&!!saved.notificationsPaused;for(const id of saved.trackedJobs||[])jobs.set(id,{room});completionNotices.push(...(saved.notices||[]));for(const n of saved.notices||[])if(n.kind==='question')seenQuestions.add(n.question_id);waitingForUser=!!saved.waitingForUser;
      if(saved.content_id===context.content_id)previousTurn=saved.previousTurn||null;}
  }catch(e){recordStorageFailure(e);}
}
function endTone(){
  try{
    const a=new AudioContext();const o=a.createOscillator(),g=a.createGain();
    o.connect(g);g.connect(a.destination);o.frequency.setValueAtTime(660,a.currentTime);o.frequency.exponentialRampToValueAtTime(330,a.currentTime+.22);
    g.gain.setValueAtTime(.12,a.currentTime);g.gain.exponentialRampToValueAtTime(.001,a.currentTime+.3);
    o.start();o.stop(a.currentTime+.3);o.onended=()=>a.close();a.resume().catch(()=>{});
  }catch(e){record('end_tone_error',{message:String(e)});}
}
function record(type,data={}){
  audit.push({at:new Date().toISOString(),type,epoch,turn_id:turn?.turn_id,content_id:context?.content_id,...data});
  if(type==='assistant_transcript'&&data.text)waitingForUser=false;
  if(['user_transcript','assistant_transcript'].includes(type)&&data.text){
    conversationMemory.push({role:type==='user_transcript'?'user':'assistant',text:data.text});
    if(conversationMemory.length>200)conversationMemory.shift();
    saveConversation();
  }
}
async function flushAudit(){
  if(!context?.room_id||!audit.length)return;
  const entries=audit.splice(0,50);
  try{await api('/events',{room_id:context.room_id,session_id:auditSession,events:entries});}catch{audit.unshift(...entries);if(audit.length>200)audit.splice(0,audit.length-200);}
}
setInterval(flushAudit,2000);
let authVersion=0;
window.__setEditorAuth=value=>{ window.__editorBootstrap=value; authVersion++; };
function nativeCommand(command){ window.ipc?.postMessage(command); }
function isTextInput(element){
  return element instanceof Element && (element.isContentEditable || element.matches('textarea,input:not([type=button]):not([type=submit]):not([type=checkbox]):not([type=radio]):not([type=range])'));
}
// A pointer click already focuses the DOM input. Moving WebView focus again via
// IPC can move the caret away from that input (and interrupt Japanese IME).
let composingText=false;
document.addEventListener('compositionstart',()=>{composingText=true;});
document.addEventListener('compositionend',()=>{composingText=false;});
// Pointer-operated controls must not retain the editor's keyboard shortcuts.
document.addEventListener('click',e=>{
  const control=e.target.closest?.('button,a,[role=button],input[type=checkbox],input[type=radio]');
  if(control && e.detail>0){control.blur();nativeCommand('return_keyboard');}
});
document.addEventListener('change',e=>{
  if(e.target.matches?.('select,input[type=range]')){e.target.blur();nativeCommand('return_keyboard');}
});
for(const type of ['keydown','keyup'])document.addEventListener(type,e=>{
  if(e.code!=='Space' || e.isComposing || composingText || e.keyCode===229 || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey)return;
  e.preventDefault();e.stopImmediatePropagation();
  if(type==='keydown' && !e.repeat && !e.ctrlKey && !e.altKey && !e.metaKey)nativeCommand('toggle_play');
},true);
function message(text,kind='system'){
  const el=document.createElement('div'); el.className='message '+kind; el.textContent=text;
  $('log').append(el); $('log').scrollTop=$('log').scrollHeight; return el;
}
function state(text){ $('state').textContent=text; }
let errorToast='';
function clearResponseError(){if(errorToast&&$('toast').textContent===errorToast)$('toast').textContent='';errorToast='';}
function error(e){record('error',{message:e.message||String(e)});message(e.message||String(e),'error'); state('操作を完了できませんでした');errorToast=e.message||String(e);$('toast').textContent=errorToast;document.body.dataset.agent='error'; }
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function token(refresh=false){
  const previous=authVersion;
  if(refresh || !window.__editorBootstrap?.token) nativeCommand('auth');
  for(let n=0;n<60;n++){
    if(window.__editorBootstrap?.token && (!refresh || authVersion!==previous)) return window.__editorBootstrap.token;
    await delay(50);
  }
  throw Error('エディターのログイン情報を受け取れませんでした。エディターを開き直してください。');
}
async function request(url,body,method='POST'){
  for(let attempt=0;attempt<2;attempt++){
    const key=await token(attempt===1);
    const r=await fetch(url,{method,credentials:'omit',headers:{'Content-Type':'application/json',Authorization:'Bearer '+key},
      signal:AbortSignal.timeout(45000),
      ...(method==='GET'?{}:{body:JSON.stringify(body)})});
    if(r.status===401 && attempt===0) continue;
    const value=await r.json();
    if(!r.ok) throw Error(r.status===401?'ログイン情報が無効です。アプリからエディターを開き直してください。':typeof value.detail==='string'?value.detail:`接続エラー (${r.status})`);
    return value;
  }
}
const api=(path,body)=>request(base+path,body);
function target(c,frozen=false){
  if(!c)return;
  const selected=c.selected||[];
  const t=Number(c.playhead||0),stamp=`${Math.floor(t/60)}:${(t%60).toFixed(1).padStart(4,'0')}`;
  const texts=selected.map(s=>s.text).filter(Boolean);
  $('target').textContent=`${stamp} · `+(selected.length?(texts.length===1?`「${texts[0].slice(0,45)}」`:`${selected.length}個を選択中`):'音声なら画面を指して話せます');
  $('target').classList.toggle('frozen',frozen);
}
window.__updateEditorContext=c=>{
  // Browsing the library is not the end of the ongoing production conversation.
  if(context?.room_id===c.room_id && context.content_id && !c.content_id)
    c={...c,content_id:context.content_id,editor_visible:false,selected:[],visible_targets:[],pointer:{}};
  const roomChanged=context && context.room_id!==c.room_id;
  if(context && (context.content_id!==c.content_id || context.room_id!==c.room_id)){
    saveConversation();
    pendingQuestion=null;
    presentationId=null;clearProposalPlayers();$('reference-cards').replaceChildren();document.body.classList.remove('has-references');
    if(roomChanged){disconnect('room_changed');jobs.clear();announcedJobs.clear();seenQuestions.clear();completionNotices.length=0;conversationMemory.length=0;$('log').replaceChildren();notificationsPaused=false;waitingForUser=false;}
    else if(busy||active)interrupt().catch(error);
    record('editor_context_changed',{from:context.content_id,to:c.content_id,room_changed:!!roomChanged});
    targetTurn=null; previousTurn=null; $('scope').value=c.content_id===pendingNewId?'whole':'selected'; pendingNewId=null;
    $('brief').textContent='会話で決めた内容をここに残します。';
  }
  const restore=!context||roomChanged;
  context=c; if(!busy)target(c);
  if(restore)restoreConversation(c.room_id);
  $('edit-view').disabled=!c.content_id;
  if(window.__autoStartVoice&&!startingVoice){window.__autoStartVoice=false;startVoiceStage().catch(error);}
  if(!c.content_id)$('target').textContent='新しい作品を開いて、作りたい動画を伝えてください。';
};
window.__editorAck=(id,result)=>{acknowledgments.get(id)?.(result);acknowledgments.delete(id);};
async function editorAction(action){
  if(!window.ipc) return {ok:false,error:'エディター内で開いてください。画面操作はまだ実行されていません。'};
  const id=crypto.randomUUID();
  return new Promise(resolve=>{
    const timer=setTimeout(()=>{acknowledgments.delete(id);resolve({ok:false,error:'画面操作への応答がありません'});},5000);
    acknowledgments.set(id,r=>{clearTimeout(timer);resolve(r);});
    nativeCommand(JSON.stringify({request_id:id,action}));
  });
}
function setBusy(value){
  busy=value; $('new').disabled=value; $('approve').disabled=value; $('unlock').disabled=value;
  // Keep both input channels available so a correction can interrupt an answer.
  $('send').textContent=value?'訂正を伝える':'送る';
  if(!value){target(context);state(micOn?'聞いています':'入力できます');}
}
function send(e){if(dc?.readyState!=='open')throw Error('会話への接続が切れています');dc.send(JSON.stringify(e));}
async function cancelTurn(b){
  if(b) return api('/cancel',{room_id:b.context.room_id,turn_id:b.turn_id,name:'cancel'});
}
async function interrupt(){
  reasonController?.abort();reasonController=null;reasonRunning=false;relayQueue.length=0;relayActive=false;
  if(activeNotice&&!activeNotice.spoken)completionNotices.unshift(activeNotice);
  activeNotice=null;audioPlaying=false;
  const old=turn; turn=null; epoch++; active=false; answer=null;
  if(dc?.readyState==='open'){
    send({type:'response.cancel'}); send({type:'output_audio_buffer.clear'});
  }
  const canceled=await cancelTurn(old);
  if(canceled?.committed_count) nativeCommand('refresh');
}
async function begin(c,mode,text='',expected=epoch){
  if(!c?.content_id)throw Error('動画を開くか「新しい作品」を押してください');
  const pointer=mode==='voice' && c.pointer && Date.now()-c.pointer.at_ms<10000 ? c.pointer : {};
  // Audit upload must never delay the next spoken instruction.
  flushAudit().catch(()=>{});
  const b=await api('/begin',{...c,pointer,reference_focus:referenceFocus,input_mode:mode,utterance:text,previous_turn:previousTurn,target_turn:mode==='voice'?targetTurn:null,scope_mode:$('scope').value});
  if(expected!==epoch){await cancelTurn(b);return null;}
  turn=b; previousTurn=b.turn_id; saveConversation(); b.mode=mode; target(c,true);
  retryCount=0;record('utterance_started',{mode,text,playhead:c.playhead});
  $('brief').textContent=Object.entries(b.context.creative_brief||{}).map(([k,v])=>`${({intent:'意図',taste:'テイスト',references:'参考',constraints:'守ること',proposals:'提案'})[k]||k}：${v}`).join('\n')||'まだ決まっていません';
  return b;
}
async function addContext(b,myEpoch){
  for(const id of contextItems)send({type:'conversation.item.delete',item_id:id,event_id:'drop_'+id});
  contextItems=[];
  const contextId='ctx_'+crypto.randomUUID().replaceAll('-','').slice(0,24);contextItems.push(contextId);
  // UI state is background, never an additional user request or unsolicited image.
  for(const id of pictureItems)send({type:'conversation.item.delete',item_id:id,event_id:'drop_'+id});
  pictureItems=[];
  send({type:'conversation.item.create',item:{id:contextId,type:'message',role:'system',content:[{type:'input_text',text:(waitingForUser?'今はユーザーが考えたり素材を探したりしている待機中です。独り言や考え途中の発話にはwait_for_userで無言を保ち、あなたへ向けた質問・依頼になった時に答えてください。\n':'')+'アプリの背景情報です。発言ではありません。画面・選択・過去の編集は必要な時にread_editor_contextで参照できます。referencesは候補一覧で通常は選んだ一つだけが表示されます。reference_focusが表示中の候補です。候補名や番号で説明します。説明を求められたことは意味しません。\n'+JSON.stringify({production:b.context.production,pending_question:pendingQuestion,waiting_for_user:waitingForUser,notifications_paused:notificationsPaused,references:b.context.presentation?.items,reference_focus:referenceFocus})}]}});
}
async function addPicture(image,label='合成した映像'){
  const budget=Math.min(pc?.sctp?.maxMessageSize||64000,64000)-4096;
  const originalBytes=image.length;
  if(image.length>budget){
    const picture=new Image();picture.src=image;await picture.decode();
    const bitmap=await createImageBitmap(picture);
    const canvas=document.createElement('canvas');
    let width=Math.min(bitmap.width,960),quality=.8;
    do {
      canvas.width=Math.round(width);canvas.height=Math.round(width*bitmap.height/bitmap.width);
      canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);
      image=canvas.toDataURL('image/jpeg',quality);
      if(quality>.5)quality-=.15;else width*=.8;
    }while(image.length>budget && width>160);
    bitmap.close();
    if(image.length>budget)throw Error('確認画像を送れるサイズにできませんでした');
  }
  record('image_transport',{originalBytes,sentBytes:image.length,maxMessageSize:pc?.sctp?.maxMessageSize});
  while(pictureItems.length>=2){const id=pictureItems.shift();send({type:'conversation.item.delete',item_id:id,event_id:'drop_'+id});}
  const id='pic_'+crypto.randomUUID().replaceAll('-','').slice(0,24);pictureItems.push(id);
  send({type:'conversation.item.create',item:{id,type:'message',role:'user',content:[{type:'input_text',text:label},{type:'input_image',image_url:image}]}});
}
function handleResponseError(err){
  record('response_error',{code:err?.code,message:err?.message});
  if(activeNotice){
    const failed=activeNotice;activeNotice=null;active=false;audioPlaying=false;setBusy(false);
    if(!failed.spoken&&(failed.retries||0)<2){
      failed.retries=(failed.retries||0)+1;completionNotices.unshift(failed);noticeRetryAt=Date.now()+3000;
    }else message('音声通知を送れませんでした。結果は会話欄に表示しています。');
    return;
  }
  if(err?.code==='session_expired'){renewSession().catch(error);return;}
  if(/rate.limit/i.test((err?.code||'')+' '+(err?.message||'')) && retryCount<3 && turn){
    if(retryTimer)return;
    const seconds=Math.max(2,Math.ceil(Number(err.message?.match(/try again in ([\d.]+)s/i)?.[1]||5)));
    const savedEpoch=epoch;retryCount++;active=false;setBusy(false);
    state(`接続が混み合っています。${seconds}秒後に続きを再開します。`);
    retryTimer=setTimeout(()=>{retryTimer=null;if(savedEpoch===epoch&&dc?.readyState==='open'){
      setBusy(true);respond();
    }},seconds*1000);return;
  }
  setBusy(false);error(Error(/rate.limit/i.test(err?.message||'')?'接続の混雑が続いています。少し待ってからもう一度伝えてください。':err?.message||'応答を完了できませんでした。'));
}
function respond(){
  runReasoning().catch(e=>{if(e.name!=='AbortError'){error(e);setBusy(false);}});
}
function speechText(text){
  return text.replace(/!\[([^\]]*)\]\([^)]*\)/g,'$1').replace(/\[([^\]]+)\]\([^)]*\)/g,'$1')
    .replace(/[*`#]/g,'').replace(/^\s*[-+]\s+/gm,'').trim();
}
function queueSpeech(text,myEpoch){
  text=speechText(text);
  if(!text.trim()||!micOn||myEpoch!==epoch)return;
  record('voice_chunk_queued',{characters:text.length,turn_id:turn?.turn_id});
  relayQueue.push({text,epoch:myEpoch});pumpSpeech();
}
function pumpSpeech(){
  if(relayActive||audioPlaying||speech||activeNotice||dc?.readyState!=='open'||!micOn)return;
  while(relayQueue.length&&relayQueue[0].epoch!==epoch)relayQueue.shift();
  const item=relayQueue.shift();if(!item)return;
  relayActive=true;active=true;
  send({type:'response.create',response:{metadata:{editor_epoch:String(epoch),editor_relay:'1'},conversation:'none',
    output_modalities:['audio'],tool_choice:'none',
    instructions:'入力の文章だけをそのまま日本語で読み上げてください。追加や言い換えは不要です。',
    input:[{type:'message',role:'user',content:[{type:'input_text',text:item.text}]}]}});
}
async function runReasoning(){
  const b=turn,myEpoch=epoch;if(!b||reasonRunning)return;
  const controller=new AbortController();reasonController=controller;reasonRunning=true;setBusy(true);answer=null;
  let outputs=[],spokenBuffer='',fullText='';
  try{
    for(let round=0;round<12;round++){
      state('考えています…');b.astraOutputs=[];
      const key=await token();
      const r=await fetch(base+'/reason',{method:'POST',credentials:'omit',signal:controller.signal,
        headers:{Authorization:'Bearer '+key,'Content-Type':'application/json'},
        body:JSON.stringify({room_id:b.context.room_id,turn_id:b.turn_id,outputs,
          runtime:{waiting_for_user:waitingForUser,notifications_paused:notificationsPaused,pending_question:pendingQuestion}})});
      if(!r.ok){const v=await r.json();throw Error(v.detail||'会話に接続できませんでした');}
      const reader=r.body.getReader(),decoder=new TextDecoder();let pending='',done=false,hasTools=false;
      async function consume(line){
        if(!line.trim())return;
        const event=JSON.parse(line);if(myEpoch!==epoch)throw new DOMException('Interrupted','AbortError');
        if(event.type==='error')throw Error(event.message);
        if(event.type==='text'){
          if(!answer){answer=message('','assistant');record('reasoning_text_started',{turn_id:b.turn_id});}waitingForUser=false;answer.textContent+=event.delta;fullText+=event.delta;spokenBuffer+=event.delta;
          $('log').scrollTop=$('log').scrollHeight;
          const boundary=spokenBuffer.match(/^([\s\S]*?[。！？\n])([\s\S]*)$/);
          if(boundary){queueSpeech(boundary[1],myEpoch);spokenBuffer=boundary[2];}
        }else if(event.type==='tool'){
          queueSpeech(spokenBuffer,myEpoch);spokenBuffer='';
          await onEvent({type:'response.function_call_arguments.done',name:event.name,call_id:event.call_id,arguments:event.arguments,astra:true});
        }else if(event.type==='done'){done=true;hasTools=event.has_tools;record('reasoning_response',{model:'gpt-6-astra',usage:event.usage});}
      }
      while(true){
        const part=await reader.read();pending+=decoder.decode(part.value||new Uint8Array(),{stream:!part.done});
        let at;while((at=pending.indexOf('\n'))>=0){const line=pending.slice(0,at);pending=pending.slice(at+1);await consume(line);}
        if(part.done){if(pending.trim())await consume(pending);break;}
      }
      if(!done)throw Error('会話の接続が途中で切れました。指示は記録されています。');
      outputs=b.astraOutputs;
      if(!hasTools||b.silent){b.silent=false;break;}
      if(round===11)throw Error('処理の確認が続いています。記録した実行結果から続けられます。');
    }
    queueSpeech(spokenBuffer,myEpoch);
  }finally{
    if(fullText&&context?.room_id===b.context.room_id)record('assistant_transcript',{text:fullText,turn_id:b.turn_id,content_id:b.context.content_id,source:'gpt-6-astra'});
    if(myEpoch===epoch){reasonRunning=false;reasonController=null;b.hadTools=false;setBusy(false);pumpSpeech();}
  }
}
async function connect(){
  if(dc?.readyState==='open')return;
  if(connecting)return connecting;
  const gen=generation;
  connecting=(async()=>{
    state('会話に接続しています…');
    record('connection_stage',{stage:'session'});
    const s=await api('/session',{});if(gen!==generation)return;
    pc=new RTCPeerConnection();audio=new Audio();audio.autoplay=true;
    pc.ontrack=e=>{if(gen!==generation||!audio)return;audio.srcObject=e.streams[0];audio.play().catch(()=>{});};
    pc.addTransceiver('audio',{direction:'sendrecv'});dc=pc.createDataChannel('oai-events');
    let resolveOpen,rejectOpen;
    const opened=new Promise((res,rej)=>{resolveOpen=res;rejectOpen=rej;});
    dc.onopen=()=>{connectedAt=Date.now();record('connection_stage',{stage:'ready'});resolveOpen();state('接続しました');};
    dc.onerror=e=>record('channel_error',{message:e.error?.message||String(e)});
    dc.onclose=()=>{record('channel_closed',{maxMessageSize:pc?.sctp?.maxMessageSize});rejectOpen(Error('接続が閉じられました'));if(gen===generation)recoverConnection('channel_closed');};
    pc.onconnectionstatechange=()=>{
      if(gen!==generation)return;
      if(pc?.connectionState==='failed')recoverConnection('peer_failed');
      if(pc?.connectionState==='disconnected')setTimeout(()=>{
        if(gen===generation&&pc?.connectionState==='disconnected')recoverConnection('peer_disconnected');
      },8000);
    };
    dc.onmessage=e=>{
      if(gen!==generation)return;
      const event=JSON.parse(e.data);
      if(event.type==='output_audio_buffer.started'){audioPlaying=true;if(activeNotice)activeNotice.audioStarted=true;record('voice_output_started',{turn_id:turn?.turn_id});}
      if(['output_audio_buffer.stopped','output_audio_buffer.cleared'].includes(event.type)){audioPlaying=false;if(activeNotice&&event.type==='output_audio_buffer.stopped'){activeNotice.audioEnded=true;finishNotice();}pumpSpeech();}
      if(event.type==='input_audio_buffer.speech_started'){startSpeech(event.item_id).catch(error);return;}
      if(event.type==='input_audio_buffer.speech_stopped'){stopSpeech().catch(e=>{error(e);setBusy(false);});return;}
      if(event.type==='response.created'){responses.set(event.response.id,Number(event.response.metadata?.editor_epoch??epoch));if(event.response.metadata?.editor_relay==='1')relayResponses.add(event.response.id);}
      queue=queue.then(()=>gen===generation?onEvent(event):null).catch(e=>{if(gen===generation){error(e);setBusy(false);}});
    };
    const offer=await pc.createOffer();await pc.setLocalDescription(offer);
    record('connection_stage',{stage:'handshake'});
    const r=await fetch('https://api.openai.com/v1/realtime/calls',{method:'POST',headers:{Authorization:'Bearer '+s.value,'Content-Type':'application/sdp'},body:offer.sdp,signal:AbortSignal.timeout(30000)});
    if(!r.ok)throw Error(`会話への接続に失敗 (${r.status})`);
    if(gen!==generation)return;
    await pc.setRemoteDescription({type:'answer',sdp:await r.text()});
    record('connection_stage',{stage:'channel'});
    let timer;try{await Promise.race([opened,new Promise((_,rej)=>{timer=setTimeout(()=>rej(Error('会話への接続がタイムアウトしました')),25000);})]);}finally{clearTimeout(timer);}
    if(conversationMemory.length)send({type:'conversation.item.create',item:{type:'message',role:'system',content:[{type:'input_text',text:'接続更新前の会話記録です。未完了の仕事の状態はproject_statusで確認し、過去の発言だけで完了・制作中と判断しない。\n'+JSON.stringify(conversationMemory)}]}});
  })();
  try{await connecting;}catch(e){disconnect('connect_error',true);throw e;}finally{connecting=null;}
}
async function recoverConnection(reason){
  if(renewing)return;
  const wanted=micOn;
  disconnect(reason,true);
  const id=++recoveryId;renewing=true;
  $('toast').textContent='音声の接続が切れました。再接続しています…';endTone();
  try{
    for(let attempt=0;attempt<3;attempt++){
      await delay(1000*(attempt+1));if(id!==recoveryId)return;
      try{
        await connect();if(id!==recoveryId)return;
        if(wanted)await toggleMic();if(id!==recoveryId)return;
        if(wanted&&!micOn)throw Error('マイクを再開できませんでした');
        record('connection_recovered',{reason,attempt:attempt+1});$('toast').textContent='音声の接続が戻りました';return;
      }catch(e){record('reconnect_failed',{attempt:attempt+1,message:String(e)});}
    }
    if(id===recoveryId){disconnect('recovery_exhausted',true);$('toast').textContent='音声の接続が切れています。マイクを押すと会話の続きから再開できます。';endTone();}
  }finally{renewing=false;}
}
async function renewSession(){
  if(renewing)return;renewing=true;
  const restoreMic=micOn,prior=previousTurn;
  disconnect('session_renewal',true);previousTurn=prior;
  const renewalGeneration=generation;
  state('会話の接続を更新しています。制作は継続中です。');
  try{await connect();if(generation!==renewalGeneration)return;if(restoreMic)await toggleMic();record('session_renewed');}
  catch(e){$('toast').textContent='音声の接続を更新できませんでした。マイクを押して再開してください。';endTone();throw e;}
  finally{renewing=false;}
}
setInterval(()=>{if(connectedAt&&Date.now()-connectedAt>55*60*1000&&dc?.readyState==='open'&&!busy&&!active&&!speech&&!renewing)renewSession().catch(error);},10000);
async function startSpeech(itemId){
  const captured=structuredClone(context), previous=busy||active||audioPlaying||relayActive||relayQueue.length;
  if(itemId&&!speechItems.has(itemId))speechItems.set(itemId,{context:captured,text:null,submitted:false,recorded:false});
  if(speechItems.size>200)speechItems.delete(speechItems.keys().next().value);
  const stopped=previous?interrupt():Promise.resolve();
  if(!previous)epoch++;
  speech={captured,epoch,stopped,itemId};setBusy(false);state('聞いています…');
}
async function stopSpeech(){
  const s=speech;speech=null;if(!s)return;
  setBusy(true);await s.stopped;if(s.epoch!==epoch)return;
  // Include pointing performed during the utterance while retaining its timestamp.
  if(context?.content_id===s.captured?.content_id && (context.pointer?.at_ms||0)>(s.captured.pointer?.at_ms||0)){
    s.captured.pointer=structuredClone(context.pointer);s.captured.visible_targets=structuredClone(context.visible_targets);
  }
  let text=pendingTranscripts.get(s.itemId);
  if(text===undefined){
    text=await new Promise(resolve=>{
      const timer=setTimeout(()=>{transcriptWaiters.delete(s.itemId);resolve('');},10000);
      transcriptWaiters.set(s.itemId,t=>{clearTimeout(timer);transcriptWaiters.delete(s.itemId);resolve(t);});
    });
  }
  if(s.epoch!==epoch)return;
  pendingTranscripts.delete(s.itemId);
  if(!String(text||'').trim()){
    record('non_speech_ignored',{item_id:s.itemId});
    if(s.itemId&&dc?.readyState==='open')send({type:'conversation.item.delete',item_id:s.itemId,event_id:'drop_'+s.itemId});
    setBusy(false);return;
  }
  // VAD can end one sentence and start the next before /begin finishes. Preserve
  // every completed sentence, including those whose response was interrupted.
  const fragments=[...speechItems.entries()].filter(([id,v])=>!v.submitted&&v.text&&v.context?.room_id===s.captured.room_id&&v.context?.content_id===s.captured.content_id);
  const fullText=fragments.length?fragments.map(([,v])=>v.text).join('\n'):text;
  const b=await begin(s.captured,'voice',fullText,s.epoch);if(!b)return;
  for(const [,v] of fragments)v.submitted=true;
  if(!speechItems.get(s.itemId)?.recorded)record('user_transcript',{turn_id:b.turn_id,text});
  if(s.itemId){
    audioTurns.set(s.itemId,b.turn_id);
    pendingTranscripts.delete(s.itemId);
    if(audioTurns.size>100)audioTurns.delete(audioTurns.keys().next().value);
  }
  await addContext(b,s.epoch);if(s.epoch===epoch)respond();
}
async function onEvent(e){
  const id=e.response_id||e.response?.id, eventEpoch=responses.get(id);
  if(id && eventEpoch!==undefined && eventEpoch!==epoch)return;
  if(relayResponses.has(id)){
    if(e.type==='response.done'){
      relayResponses.delete(id);relayActive=false;active=false;
      if(e.response?.status==='failed')handleResponseError(e.response.status_details?.error);
      pumpSpeech();
    }
    return;
  }
  if(e.type==='conversation.item.input_audio_transcription.completed'){
    let part=speechItems.get(e.item_id);
    if(!part){part={context:structuredClone(context),submitted:false,recorded:false};speechItems.set(e.item_id,part);}
    part.text=e.transcript;
    if(e.transcript?.trim()&&!part.recorded){part.recorded=true;record('user_transcript',{item_id:e.item_id,turn_id:audioTurns.get(e.item_id),text:e.transcript});}
    transcriptWaiters.get(e.item_id)?.(e.transcript);
    const tid=audioTurns.get(e.item_id);
    if(!tid){pendingTranscripts.set(e.item_id,e.transcript);if(pendingTranscripts.size>100)pendingTranscripts.delete(pendingTranscripts.keys().next().value);}
    if(e.transcript?.trim())message(e.transcript,'user');return;
  }
  if(['response.output_audio_transcript.done','response.audio_transcript.done','response.output_text.done'].includes(e.type)){if(activeNotice){activeNotice.transcript=e.transcript||e.text;record('completion_audio_generated',{job_id:activeNotice.job_id});}record('assistant_transcript',{text:e.transcript||e.text});return;}
  if(['response.output_audio_transcript.delta','response.audio_transcript.delta','response.output_text.delta'].includes(e.type)){
    if(!answer)answer=message('','assistant');answer.textContent+=e.delta||'';$('log').scrollTop=$('log').scrollHeight;return;
  }
  if(e.type==='response.function_call_arguments.done'){
    const b=turn,myEpoch=epoch;let result;
    try{
      if(!b)throw Error('指示は中止されました');
      state('確認・編集しています…');
      record('tool_started',{name:e.name,args:JSON.parse(e.arguments||'{}')});
      if(['batch_edit','timeline_edit'].includes(e.name)){
        const parsed=JSON.parse(e.arguments||'{}');
        const ops=parsed.operations||[{op:parsed.op,args:parsed.args||{}}];
        const ids=ops.flatMap(o=>[o.args?.clip_id,...(o.args?.clip_ids||[])]).filter(id=>typeof id==='string');
        directOperations.set(e.call_id,{tool:e.name,category:'editing',clip_ids:ids});publishWorkActivity();
      }
      const args=JSON.parse(e.arguments||'{}');
      if(e.name==='read_editor_context')result={ok:true,...b.context};
      else if(e.name==='wait_for_user'){waitingForUser=true;saveConversation();b.silent=true;result={ok:true};}
      else if(e.name==='resume_conversation'){waitingForUser=false;saveConversation();result={ok:true};}
      else if(e.name==='answer_question'){
        result=(await answerCurrentQuestion(args.text,args.question_id))||{ok:false,error:'現在の質問はありません。回答は会話に残っています。制作の状態を確認してください。'};
      }else if(e.name==='set_voice_notifications'){
        notificationsPaused=args.paused;if(args.paused)waitingForUser=true;saveConversation();
        if(notificationsPaused){completionNotices.length=0;b.silent=true;}
        result={ok:true,paused:notificationsPaused};
      }else result=await api('/tool',{room_id:b.context.room_id,turn_id:b.turn_id,name:e.name,args});
      record('tool_finished',{name:e.name,result:{...result,image:result.image?'[image]':undefined}});
      if(myEpoch!==epoch)return;
      if(result.presentation){renderReferences(result.presentation);record('references_displayed',{search_ms:result.elapsed_ms,first_results_ms:result.first_results_ms,count:result.presentation.items.length});}
      if(result.editor_action){
        const displayed=await editorAction(result.editor_action);
        if(myEpoch!==epoch)return;
        if(displayed.ok && result.editor_action.kind==='focus'){targetTurn=b.turn_id;}
        result={...result,...displayed};
      }
      if(result.committed){nativeCommand('refresh');message('変更を反映しました。');targetTurn=null;}
      if(result.image&&!e.astra){await addPicture(result.image);const {image,...details}=result;result={...details,note:'確認用の画像を添付しました'};}
      if(result.saved)$('brief').textContent=Object.values(result.saved).join('\n');
      if(result.presentation)renderReferences(result.presentation);
      if(result.job_id){jobs.set(result.job_id,{room:b.context.room_id});message(result.state==='instruction_pending'?'追加指示を送りました。制作側の受領を待っています。':'制作を依頼しました。進行状況を下に表示します。');}
    }catch(ex){record('tool_client_error',{name:e.name,message:ex.message});result={ok:false,error:ex.message};}
    finally{directOperations.delete(e.call_id);publishWorkActivity();}
    if(myEpoch!==epoch)return;
    if(e.astra){b.astraOutputs.push({call_id:e.call_id,result});return;}
    b.hadTools=true;
    send({type:'conversation.item.create',item:{type:'function_call_output',call_id:e.call_id,output:JSON.stringify(result)}});return;
  }
  if(e.type==='response.done'){
    record('response_done',{status:e.response?.status,details:e.response?.status_details,usage:e.response?.usage});
    active=false;
    if(e.response?.status==='completed')clearResponseError();
    if(activeNotice&&e.response?.status==='completed'){activeNotice.generated=true;finishNotice();return;}
    if(e.response?.status==='incomplete'){
      if(e.response.status_details?.reason==='max_output_tokens' && turn && (turn.continuations||0)<2){
        turn.continuations=(turn.continuations||0)+1;
        send({type:'conversation.item.create',item:{type:'message',role:'user',content:[{type:'input_text',text:'直前の応答は長さの上限で途中終了しました。実行済みの操作を重複させず、未完了の確認・編集を続けてください。'}]}});
        respond();return;
      }
      setBusy(false);error(Error('応答が途中で終了しました。編集の実行状況を確認してください。'));return;
    }
    if(e.response?.status==='failed'){
      handleResponseError(e.response.status_details?.error);return;
    }
    if(e.response?.status==='cancelled'){setBusy(false);return;}
    if(turn?.silent){turn.hadTools=false;turn.silent=false;setBusy(false);return;}
    if(turn?.hadTools){turn.hadTools=false;respond();}else setBusy(false);
    return;
  }
  if(e.type==='error'){
    if(e.error?.event_id?.startsWith('drop_'))return;
    if(['response_cancel_not_active','output_audio_buffer_clear_not_active'].includes(e.error?.code))return;
    active=false;handleResponseError(e.error);
  }
}
async function submit(){
  const text=$('input').value.trim();if(!text)return;clearResponseError();
  const captured=structuredClone(context);
  if(busy||active||audioPlaying||relayActive||relayQueue.length)await interrupt();else epoch++;
  const myEpoch=epoch;setBusy(true);message(text,'user');$('input').value='';
  record('user_transcript',{text,input_mode:'text'});
  try{await connect();if(myEpoch!==epoch)return;const b=await begin(captured,'text',text,myEpoch);if(!b)return;
    await addContext(b,myEpoch);send({type:'conversation.item.create',item:{type:'message',role:'user',content:[{type:'input_text',text}]}});respond();
  }catch(e){error(e);setBusy(false);}
}
async function toggleMic(){
  if(micOn){record('microphone_paused');endTone();micOn=false;mic?.getTracks().forEach(t=>t.enabled=false);$('mic').setAttribute('aria-label','マイクで話す');$('mic').classList.remove('live');state('マイクを停止しました');return;}
  try{
    const gen=generation;
    await connect();
    if(gen!==generation)return;
    if(!mic){const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
      if(gen!==generation){stream.getTracks().forEach(t=>t.stop());return;}
      mic=stream;mic.getAudioTracks()[0].onended=()=>{if(gen===generation&&micOn)recoverConnection('microphone_ended');};
      await pc.getSenders().find(s=>!s.track||s.track.kind==='audio').replaceTrack(mic.getAudioTracks()[0]);}
    if(gen!==generation)return;
    micOn=true;mic.getTracks().forEach(t=>t.enabled=true);$('mic').setAttribute('aria-label','マイクを止める');$('mic').classList.add('live');state('聞いています');$('toast').textContent='';
  }catch(e){mic?.getTracks().forEach(t=>t.stop());mic=null;error(e);}
}
function disconnect(reason='user',internal=false){
  reasonController?.abort();reasonController=null;reasonRunning=false;relayQueue.length=0;relayActive=false;relayResponses.clear();
  if(!internal)recoveryId++;
  record('disconnected',{reason:typeof reason==='string'?reason:'user',mic_on:micOn});saveConversation();
  if(!internal&&(micOn||connectedAt))endTone();
  if(activeNotice)completionNotices.unshift(activeNotice);audioPlaying=false;activeNotice=null;
  for(const resolve of [...transcriptWaiters.values()])resolve('');
  connectedAt=0;
  flushAudit();if(retryTimer)clearTimeout(retryTimer);retryTimer=null;contextItems=[];pictureItems=[];
  const old=turn;generation++;epoch++;turn=null;cancelTurn(old).catch(()=>{});
  queue=Promise.resolve();responses.clear();speech=null;micOn=false;mic?.getTracks().forEach(t=>t.stop());mic=null;
  const channel=dc;dc=null;if(channel)channel.onclose=null;channel?.close();pc?.close();pc=null;
  if(audio){audio.pause();audio.srcObject=null;audio=null;}active=false;setBusy(false);
  $('mic').setAttribute('aria-label','マイクで話す');$('mic').classList.remove('live');state('会話を終了しました');
}
$('send').onclick=submit;$('mic').onclick=()=>startVoiceStage().catch(error);$('disconnect').onclick=disconnect;
// Files can be supplied while speaking, without submitting a new production job.
const attachmentInput=document.createElement('input');
attachmentInput.type='file';attachmentInput.multiple=true;attachmentInput.accept='image/*,video/*,audio/*';attachmentInput.hidden=true;
const attachmentButton=document.createElement('button');
attachmentButton.id='attach';attachmentButton.textContent='＋';attachmentButton.title='素材を渡す';attachmentButton.setAttribute('aria-label','素材を渡す');
$('dock').prepend(attachmentButton);document.body.append(attachmentInput);
attachmentButton.onclick=()=>attachmentInput.click();
async function supplyFiles(files){
  if(!files.length)return;
  await ensureStageContent();
  const captured={room_id:context.room_id,content_id:context.content_id};
  attachmentButton.disabled=true;
  try{
    for(const file of files){
      $('toast').textContent=file.name+' を取り込んでいます';
      const data=new FormData();data.append('file',file);
      let asset;
      for(let attempt=0;attempt<2;attempt++){
        const auth=await token(attempt===1);
        const r=await fetch('/api/v1/production-assets/upload?room_id='+encodeURIComponent(captured.room_id),{
          method:'POST',credentials:'omit',headers:{Authorization:'Bearer '+auth},body:data});
        if(r.status===401&&attempt===0)continue;
        asset=await r.json();if(!r.ok)throw Error(typeof asset.detail==='string'?asset.detail:'素材を取り込めませんでした');
        break;
      }
      if(!asset?.id)throw Error('素材の登録結果を確認できませんでした');
      await api('/reference',{...captured,source:asset.id});
      if(context?.room_id===captured.room_id&&context?.content_id===captured.content_id){
        const text='素材を添付しました: '+file.name+' (asset_id: '+asset.id+')。用途は会話の意図に沿って判断してください。';
        message(file.name+' を追加しました','system');record('material_attached',{asset_id:asset.id,filename:file.name});
        if(dc?.readyState==='open')send({type:'conversation.item.create',item:{type:'message',role:'user',content:[{type:'input_text',text}]}});
      }
    }
    $('toast').textContent='素材を追加しました';setTimeout(()=>{if($('toast').textContent==='素材を追加しました')$('toast').textContent='';},2500);
  }finally{attachmentButton.disabled=false;attachmentInput.value='';}
}
attachmentInput.onchange=()=>supplyFiles([...attachmentInput.files]).catch(error);
document.addEventListener('dragover',e=>{if([...e.dataTransfer.types].includes('Files'))e.preventDefault();});
document.addEventListener('drop',e=>{if(e.dataTransfer.files.length){e.preventDefault();supplyFiles([...e.dataTransfer.files]).catch(error);}});
document.addEventListener('paste',e=>{const files=[...e.clipboardData.files];if(files.length){e.preventDefault();supplyFiles(files).catch(error);}});
$('close').onclick=()=>{disconnect();nativeCommand('close');};
$('pick').onclick=()=>nativeCommand('pick');
$('clear').onclick=()=>{targetTurn=null;nativeCommand('clear_focus');};
$('undo').onclick=async()=>{try{await interrupt();nativeCommand('undo');setBusy(false);}catch(e){error(e);}};
$('input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&!composingText&&e.keyCode!==229){e.preventDefault();submit();}};
$('new').onclick=async()=>{try{
  if(!context?.room_id)throw Error('制作ルームを開いてください');
  if(context.unsaved)throw Error('手編集を保存中です。少し待ってください');
  disconnect();const v=await api('/new',{room_id:context.room_id});pendingNewId=v.content_id;
  $('scope').value='whole';nativeCommand('open:'+v.content_id);message('どんな動画を作りたいか教えてください。');
}catch(e){error(e);}};
async function approve(value){
  if(!context?.selected?.length){message('承認する範囲を選択してください');return;}
  try{await api('/approval',{...context,approved:value});nativeCommand('refresh');message(value?'選択範囲を承認しました。':'承認を解除しました。');}catch(e){error(e);}
}
$('approve').onclick=()=>approve(true);$('unlock').onclick=()=>approve(false);
window.addEventListener('beforeunload',disconnect);
let statusPending=false;
const directOperations=new Map();
let productionSnapshot={highlights:[],active_count:0,label:null};
function publishWorkActivity(){
  if(!context?.content_id)return;
  nativeCommand(JSON.stringify({action:{kind:'production_activity',content_id:context.content_id,
    ...productionSnapshot,operations:[...productionSnapshot.highlights,...directOperations.values()]}}));
}

const announcedJobs=new Set();
function finishNotice(){
  if(!activeNotice?.generated||!activeNotice.audioStarted||!activeNotice.audioEnded)return;
  const notice=activeNotice;notice.spoken=true;spokenJobs.add(notice.job_id);
  record('completion_spoken',{job_id:notice.job_id,text:notice.transcript});
  if(notice.transcript)send({type:'conversation.item.create',item:{type:'message',role:'assistant',content:[{type:'output_text',text:notice.transcript}]}});
  activeNotice=null;active=false;saveConversation();setBusy(false);pumpSpeech();
}
async function announceCompletion(){
  if(activeNotice||relayActive||relayQueue.length||reasonRunning)return;
  if(!completionNotices.length)return;
  const blocked=notificationsPaused?'notifications_paused':!micOn?'microphone_off':dc?.readyState!=='open'?'disconnected':busy?'turn_pending':active?'responding':speech?'user_speaking':audioPlaying?'audio_playing':renewing?'reconnecting':Date.now()<noticeRetryAt?'retry_delay':'';
  if(blocked){if(blocked!==lastNoticeBlock){record('completion_waiting',{reason:blocked,job_id:completionNotices[0].job_id});lastNoticeBlock=blocked;}return;}
  lastNoticeBlock='';
  const notice=completionNotices.shift();
  if(notice.kind==='question'&&notice.question_id!==pendingQuestion?.id)return;
  if(notice.content_id!==context?.content_id||notice.room_id!==context?.room_id)return;
  active=true;answer=null;
  activeNotice={...notice,generated:false,audioStarted:false,audioEnded:false};
  const delivery=activeNotice;
  if(turn)turn.hadTools=false;
  record('completion_announcement_requested',{job_id:notice.job_id,queued_ms:notice.queued_at?Date.now()-notice.queued_at:null});
  const noticeEpoch=epoch;
  try{
    const result=await api('/notice',{room_id:notice.room_id,content_id:notice.content_id,job_id:notice.job_id,kind:notice.kind||'completion',question_id:notice.question_id});
    if(noticeEpoch!==epoch||activeNotice!==delivery)return;
    if(!result.text)throw Error('作業の報告を取得できませんでした');
  send({type:'response.create',response:{metadata:{editor_epoch:String(epoch)},output_modalities:['audio'],tool_choice:'none',conversation:'none',
    input:[{type:'message',role:'user',content:[{type:'input_text',text:speechText(result.text)}]}],
    instructions:'入力の文章だけをそのまま日本語で読み上げてください。追加や言い換えは不要です。'}});
  }catch(e){if(noticeEpoch===epoch&&activeNotice===delivery)handleResponseError({message:e.message});}
}
setInterval(announceCompletion,500);
function renderProductionStatus(s,captured){
  if(s.clip_count>0&&draftWaitingCid===captured.content_id){
    draftWaitingCid=null;window.__setStageMode(false);nativeCommand('stage_compact');nativeCommand('refresh');
  }
  if(s.presentation)renderReferences(s.presentation);
  stageWorking=(s.jobs||[]).some(j=>['running','queued'].includes(j.status)&&!j.question);
  const currentQuestion=(s.jobs||[]).find(j=>j.question&&(['running','queued'].includes(j.status)||jobs.has(j.id)))?.question||null;
  pendingQuestion=currentQuestion;
  const host=$('work-status');host.replaceChildren();
  const names={Write:'映像の編集元を作成',Edit:'映像の編集元を修正',apply_edits:'変更をまとめて反映',animate_clip:'動きを調整',prepare_motion_project:'編集元を準備',render_motion_project:'動きのある映像を書き出す',generate_video:'映像を生成',generate_image:'画像を生成',generate_speech:'声を生成',watch_render:'通しで検品',render_frame:'画面を確認',validate_draft:'編集結果を検証',auto_captions:'字幕を合わせる',browser:'サービスを操作',get_credentials:'接続を確認',WebSearch:'必要な情報を検索',WebFetch:'サービスの情報を確認',Bash:'素材・サービスを準備',Read:'資料を確認',Glob:'素材を探す',ToolSearch:'使う道具を探す'};
  const highlights=[];const phases=[];
  for(const j of (s.jobs||[])){
    const ongoing=['running','queued'].includes(j.status);
    if(!ongoing){
      if(pendingQuestion?.job_id===j.id)pendingQuestion=null;
      if(jobs.has(j.id)&&!announcedJobs.has(j.id)){
        announcedJobs.add(j.id);jobs.delete(j.id);nativeCommand('refresh');
        if(j.result?.committed&&draftWaitingCid===captured.content_id){
          draftWaitingCid=null;window.__setStageMode(false);nativeCommand('stage_compact');
        }
        const notice={room_id:captured.room_id,content_id:captured.content_id,job_id:j.id,status:j.status,queued_at:Date.now(),
          request:j.request,
          production_report_before_save:j.result?.outcome||{summary:j.result?.summary},
          final_result:{message:j.result?.message,output_url:j.result?.output_url,
            output_path:j.result?.user_output_path||j.result?.output_path,render_size:j.result?.render_size},
          current_timeline:j.result?.committed===true
            ?{saved:true,user_commit_required:false,detail:'制作担当の報告を受けた後、アプリがタイムラインへの保存を完了しました。'}
            :undefined,
          ...(typeof j.result?.committed==='boolean'?{timeline_updated:j.result.committed}:{}),...(j.error?{error:j.error}:{})};
        nativeCommand(JSON.stringify({action:{kind:'work_finished',content_id:captured.content_id,job_id:j.id,status:j.status,committed:j.result?.committed}}));
        record('production_finished',{job_id:j.id,status:j.status,committed:j.result?.committed});
        message(j.result?.outcome?.summary||j.result?.summary||(j.status==='done'?'処理が終わりました。':`作業が止まりました：${j.error||j.status}`));
        // A previous preparation result is historical once a later production
        // has started. Do not announce it as the current state minutes later.
        if(!(s.jobs||[]).some(other=>other.id!==j.id&&other.created_at>j.updated_at))completionNotices.push(notice);
      }
      continue;
    }
    const card=document.createElement('div');card.className='production-card '+j.status;
    if(j.question){
      pendingQuestion=j.question;
      if(!seenQuestions.has(j.question.id)){
        seenQuestions.add(j.question.id);message(j.question.text,'assistant');
        if(micOn&&dc?.readyState==='open'&&!notificationsPaused)completionNotices.push({kind:'question',question_id:j.question.id,room_id:captured.room_id,content_id:captured.content_id,job_id:j.id,question:j.question.text});
      }
    }
    const op=(j.activity||[]).find(a=>a.state==='running')||j.activity?.[0];
    phases.push(j.question?'返答を待っています':op?.category==='review'?'仕上がりを確認中':op?.category==='editing'?'タイムラインを編集中':op?.category==='generation'?'素材を制作中':'作業内容を確認中');
    const title=document.createElement('strong');
    title.textContent=j.question?'あなたの返答を待っています':op?.state==='running'?(names[op.tool]||names[op.tool?.split('__').at(-1)]||'内容を確認・編集'):'次の作業を判断中';
    const indicator=document.createElement('span');indicator.className='activity-indicator';
    card.append(indicator,title);
    const detail=document.createElement('div');detail.className='activity-detail';
    const elapsed=op?.started_at?Math.max(0,Math.floor(Date.now()/1000-op.started_at)):0;
    detail.textContent=ongoing?[op?.model,j.pending_instructions?'追加指示の受領待ち':'',op?.category==='generation'&&op?.state==='running'?'生成結果を待っています':'',op?.state==='running'?`${Math.floor(elapsed/60)}分${elapsed%60}秒経過`:''].filter(Boolean).join(' · '):(j.error||j.result?.summary||'');
    card.append(detail);
    const steps=document.createElement('div');steps.className='activity-steps';
    for(const [key,label] of [['inspect','確認'],['generation','素材制作'],['editing','編集'],['review','検品']]){
      const step=document.createElement('span');step.textContent=label;
      if(ongoing&&op?.state==='running'&&op.category===key)step.className='current';
      steps.append(step);
    }
    card.append(steps);host.append(card);
    if(ongoing){
      jobs.set(j.id,{room:captured.room_id});
      if(op?.state==='running'&&['editing','generation'].includes(op.category))highlights.push({clip_ids:op.clip_ids?.length?op.clip_ids:(j.selected_clips||[]).map(c=>c.id||c.clip_id).filter(Boolean),tool:op.tool,category:op.category});
    }
  }
  for(let i=completionNotices.length-1;i>=0;i--){
    const notice=completionNotices[i];
    if(notice.kind==='question')continue;
    const job=(s.jobs||[]).find(j=>j.id===notice.job_id);
    if(job&&(s.jobs||[]).some(other=>other.id!==job.id&&other.created_at>job.updated_at))completionNotices.splice(i,1);
  }
  saveConversation();
  productionSnapshot={highlights,active_count:(s.jobs||[]).filter(j=>['running','queued'].includes(j.status)).length,label:phases.length?[...new Set(phases)].join(' · '):null};
  publishWorkActivity();
}
setInterval(async()=>{
  if(statusPending || !context?.content_id)return;
  const captured=context;statusPending=true;
  try{
    const s=await api('/project-status',captured);
    if(context?.content_id!==captured.content_id || context?.room_id!==captured.room_id)return;
    renderProductionStatus(s,captured);
  }catch(e){record('production_status_error',{message:String(e)});}finally{statusPending=false;}
},3000);
let startingVoice=false,stageWorking=false,presentationId=null,draftWaitingCid=null,referenceFocus=null;
let meterContext=null,meterStream=null,meterSource=null,meter=null;
window.__setStageMode=full=>{
  document.body.classList.toggle('compact',!full);
  $('edit-view').textContent=full?'編集画面へ ↗':'会話に集中 ↗';
};
async function startVoiceStage(){
  if(renewing){disconnect('user_stopped_reconnection');return;}
  if(startingVoice)return;
  startingVoice=true;
  try{
    await ensureStageContent();
    await toggleMic();
  }finally{startingVoice=false;}
}
async function ensureStageContent(){
    if(!context?.room_id)throw Error('制作ルームを開いてください');
    if(!context.content_id){
      for(let i=0;i<50&&context.unsaved;i++)await delay(100);
      if(context.unsaved)throw Error('手編集を保存してから新しい作品を始めてください');
      const v=await api('/new',{room_id:context.room_id});pendingNewId=v.content_id;draftWaitingCid=v.content_id;
      $('scope').value='whole';nativeCommand('open:'+v.content_id);
      for(let i=0;i<100&&context?.content_id!==v.content_id;i++)await delay(100);
      if(context?.content_id!==v.content_id)throw Error('新しい作品を開けませんでした');
    }
}
$('show-chat').onclick=()=>{document.body.classList.add('drawer-open');$('input').focus();};
$('hide-chat').onclick=()=>document.body.classList.remove('drawer-open');
$('edit-view').onclick=()=>{
  const full=document.body.classList.contains('compact');
  window.__setStageMode(full);nativeCommand(full?'stage_full':'stage_compact');
};
const originalPick=$('pick').onclick;
$('pick').onclick=()=>{window.__setStageMode(false);nativeCommand('stage_compact');document.body.classList.remove('drawer-open');originalPick();};
$('hide-references').onclick=()=>{
  clearProposalPlayers();$('reference-cards').replaceChildren();document.body.classList.remove('has-references');
};
function referenceEmbed(item){
  const u=new URL(item.url,location.origin);let id=null;
  if(['youtube.com','www.youtube.com','m.youtube.com'].includes(u.hostname))id=u.searchParams.get('v')||u.pathname.match(/^\/(?:shorts|embed)\/([\w-]+)/)?.[1];
  if(u.hostname==='youtu.be')id=u.pathname.slice(1);
  if(id&&/^[\w-]{11}$/.test(id))return 'https://www.youtube-nocookie.com/embed/'+id+'?rel=0&start='+Math.floor(item.start||0)+(item.end?'&end='+Math.floor(item.end):'');
  if(u.hostname==='vimeo.com'&&/^\/\d+$/.test(u.pathname))return 'https://player.vimeo.com/video'+u.pathname+'#t='+Math.floor(item.start||0)+'s';
  return null;
}
let proposalPlayers=[];
function clearProposalPlayers(){proposalPlayers.forEach(p=>p.dispose?.());proposalPlayers=[];}
function renderReferences(p){
  if(!p?.items?.length||p.id===presentationId)return;
  presentationId=p.id;clearProposalPlayers();
  const host=$('reference-cards');host.replaceChildren();
  const tabs=document.createElement('div');tabs.className='proposal-tabs';tabs.setAttribute('role','tablist');
  const items=document.createElement('div');items.className='proposal-items';host.append(tabs,items);
  let selected=0,compare=false;
  const draw=()=>{
    clearProposalPlayers();items.replaceChildren();items.classList.toggle('comparing',compare);
    [...tabs.children].forEach((b,i)=>b.setAttribute('aria-selected',String(i===selected)));
    for(const index of compare?[...new Set([selected,(selected+1)%p.items.length])]:[selected]){
      const item=p.items[index];referenceFocus=item.id;
      const card=document.createElement('article');card.className='reference-card';card.onpointerenter=()=>referenceFocus=item.id;
      const player=createProposalPlayer(item);proposalPlayers.push(player);
      const copy=document.createElement('div');copy.className='reference-copy';
      const title=document.createElement('h2');title.textContent=item.title;
      const note=document.createElement('p');note.textContent=item.note||'';
      const actions=document.createElement('div');actions.className='reference-actions';
      const choose=document.createElement('button');choose.textContent='この方向で下書きを作る';
      choose.onclick=async()=>{try{await api('/choose',{room_id:context.room_id,content_id:context.content_id,item_id:item.id});referenceFocus=item.id;$('input').value='提案「'+item.title+'」（ID: '+item.id+'）の方向で、元の目的と素材を使って制作を進めてください。';submit();choose.blur();}catch(e){error(e);}};
      actions.append(choose);
      const sourceUrl=item.source_url||item.url;
      if(sourceUrl?.startsWith('https:')){const source=document.createElement('a');source.textContent='出典 ↗';source.href=sourceUrl;source.target='_blank';source.rel='noopener noreferrer';source.onclick=e=>{if(window.ipc){e.preventDefault();nativeCommand('external:'+sourceUrl);}};actions.append(source);}
      copy.append(title,note,actions);card.append(player,copy);items.append(card);
    }
  };
  p.items.forEach((item,i)=>{const b=document.createElement('button');b.textContent=(i+1)+' · '+item.title;b.setAttribute('role','tab');b.onclick=()=>{selected=i;draw();b.blur();};tabs.append(b);});
  if(p.items.length>1){const b=document.createElement('button');b.textContent='並べて比べる';b.onclick=()=>{compare=!compare;b.textContent=compare?'１つずつ見る':'並べて比べる';draw();b.blur();};tabs.append(b);}
  draw();document.body.classList.add('has-references');
}
function updatePresence(){
  const connected=dc?.readyState==='open';document.body.classList.toggle('connected',connected);
  const kind=$('toast').textContent?'error':audioPlaying?'speaking':speech?'listening':(busy||active||stageWorking)?'thinking':micOn?'listening':'offline';
  document.body.dataset.agent=kind;
  $('presence').setAttribute('aria-label',({speaking:'ダンが話しています',listening:'ダンが聞いています',thinking:'ダンが考えています',offline:'ダンは待機中',error:'接続を確認してください'})[kind]);
  const stream=audioPlaying?audio?.srcObject:micOn?mic:null;
  if(stream!==meterStream){
    meterStream=stream;meterSource?.disconnect();meterSource=null;meter=null;
    if(stream)try{meterContext??=new AudioContext();meterContext.resume().catch(()=>{});meterSource=meterContext.createMediaStreamSource(stream);meter=meterContext.createAnalyser();meter.fftSize=256;meterSource.connect(meter);}catch{}
  }
  let level=0;if(meter){const values=new Uint8Array(meter.fftSize);meter.getByteTimeDomainData(values);level=Math.min(1,Math.sqrt(values.reduce((s,v)=>s+(v-128)**2,0)/values.length)/24);}
  $('orb').style.setProperty('--level',level.toFixed(3));
}
setInterval(updatePresence,80);
nativeCommand('ready');
