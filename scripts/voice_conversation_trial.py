"""Actual Live audio + Astra + shared client controller, isolated from device/UI.

Synthetic Japanese speech is streamed in real time through WebRTC. Transcript
and PCM timing are captured; no existing room receives test messages. Real
history is read-only; mutating tools are refused by this diagnostic harness.
"""
import argparse,asyncio,base64,json,subprocess,time
from pathlib import Path
from datetime import datetime
import httpx
from playwright.async_api import async_playwright
from app.config import settings
from app.services import voice_live
from app.api.voicelog_routes import _CHAT_TOOLS,_chat_instructions
from app.services.command_center import INSTRUCTIONS,TOOL,execute
from app.services.chat_service import ChatService
from app.services.voice_history import room_history
from fastapi import FastAPI,Request
from fastapi.responses import StreamingResponse
import uvicorn

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.tmp/voice-conversation-trial'
USER='2582a188-ff24-4a4f-b989-6063034d90b2'
ROOM='5e43d6b8-0f68-4113-a576-01bb39b84933'
TEST_ROOM='14a5ab75-770a-4c6d-93a2-dd263b686b8b'
PHRASES={
 'date':'今日って何曜日だっけ？',
 'smalltalk':'今日ちゃんとゴミ出しできたんだ。ちょっと褒めてよ。',
 'reservation':'昨日、新幹線の予約したよね。結局取れたんだっけ？記録を調べて。',
 'status':'今、何が分かってる？',
 'correction':'新しく予約しないでね。昨日の予約がその後キャンセルされたか知りたいだけ。',
 'repeat':'つまり今は、予約が残ってるの？',
 'interrupt':'ちょっと待って、短く一言で教えて。',
 'work':'このテスト用フォルダーに、声の試験が完了しましたって書いたメモを作って。できたら教えて。',
 'work_change':'そのメモの最後に、確認済み、って追加して。',
 'end_call':'電話を切ってください。',
 'end_work_continues':'仕事はそのまま続けて、通話だけ終了してください。',
 'end_quote':'さっき電話切ってって言ったのに切れなかったんだよ。なぜだと思う？',
 'end_negation':'電話切ってほしくない。まだ話していたい。',
 'end_negation_short':'電話切ってほしくない。',
 'end_report':'電話切ってって言ったのに切れなかった。',
}

async def speech(client,name):
 path=OUT/(name+'.wav')
 text_path=OUT/(name+'.speech.txt')
 if not path.exists() or not text_path.exists() or text_path.read_text(encoding='utf-8')!=PHRASES[name]:
  r=await client.post('https://api.openai.com/v1/audio/speech',headers={'Authorization':'Bearer '+settings.OPENAI_API_KEY},
   json={'model':'gpt-4o-mini-tts','voice':'ash','input':PHRASES[name],'instructions':'自然な日本語の会話。質問を仕事仲間へ普通に話しかける声。','response_format':'wav'})
  r.raise_for_status();path.write_bytes(r.content)
  text_path.write_text(PHRASES[name],encoding='utf-8')
 return path

async def run(args):
 if args.label in PHRASES:raise ValueError('Output label must differ from speech fixture names')
 if args.speech_instructions:
  if args.deployed:raise ValueError('Instruction experiments must be isolated')
  voice_live.INSTRUCTIONS=Path(args.speech_instructions).read_text(encoding='utf-8')
 if args.deployed and 'work' in args.cases.split(','):raise ValueError('Deployed probe is read-only')
 OUT.mkdir(parents=True,exist_ok=True)
 from app.services.auth_service import create_access_token
 deployed_headers={'Authorization':'Bearer '+create_access_token(USER,'')} if args.deployed else {}
 async def deployed(path,body):
  async with httpx.AsyncClient(timeout=60) as client:
   response=await client.post(args.deployed+'/api/v1/voicelog/live/'+path,headers=deployed_headers,json=body)
   response.raise_for_status();return response.json()
 async with httpx.AsyncClient(timeout=60) as client:
  for name in args.cases.split(',')+([args.interject] if args.interject else []):await speech(client,name)
 tools=[t for t in _CHAT_TOOLS if t['name']!='look_at_screen']+[{'type':'function','name':TOOL['name'],'description':TOOL['description'],'parameters':TOOL['input_schema']}]
 if any(name.startswith('end_') for name in args.cases.split(',')):tools.append(voice_live.STANDBY_TOOL)
 instructions=_chat_instructions('Done')+'\n'+INSTRUCTIONS
 if 'work' in args.cases.split(','):
  (OUT/args.label).mkdir(exist_ok=True)
  instructions+=f'\n今回のファイル作業の試験用フォルダーは {(OUT/args.label).as_posix()}。delegate_to_danで試験用の別室へ依頼できる。外部の購入・送信・公開はしない。'
 rows=getattr(args,'history',None)
 if rows is None:
  rows=await ChatService().get_messages(ROOM,USER,limit=96)
  rows=[r for r in rows if r['created_at']<'2026-09-16T09:06:00']
 history=room_history(rows)
 sid=None;metrics=[];start=time.monotonic()
 server_app=FastAPI()
 @server_app.post('/api/backend')
 async def backend_stream(request:Request):
  data=await request.json();t=time.monotonic()
  async def events():
   if args.deployed:
    async with httpx.AsyncClient(timeout=90) as client:
     async with client.stream('POST',args.deployed+'/api/v1/voicelog/live/backend/stream',headers=deployed_headers,json={'session_id':sid,'input':data['input']}) as response:
      response.raise_for_status()
      async for line in response.aiter_lines():
       if line.startswith('data:'):
        event=json.loads(line[5:])
        if event['type']=='completed':log('backend',seconds=round(time.monotonic()-t,3),output=event['output'],deployed=True)
       yield line+'\n'
    return
   async for event in voice_live.stream_response(sid,USER,data['input']):
    if event['type']=='completed':log('backend',seconds=round(time.monotonic()-t,3),output=event['output'],backend=event.get('backend'))
    yield 'data: '+json.dumps(event,ensure_ascii=False)+'\n\n'
  return StreamingResponse(events(),media_type='text/event-stream')
 server=uvicorn.Server(uvicorn.Config(server_app,host='127.0.0.1',port=0,log_level='error'))
 server_task=asyncio.create_task(server.serve())
 while not server.started:
  if server_task.done():await server_task
  await asyncio.sleep(.05)
 trial_origin='http://localhost:'+str(server.servers[0].sockets[0].getsockname()[1])
 def log(kind,**data):
  def safe(value):
   if isinstance(value,dict):return {k:('[redacted]' if k=='voice_approval' else safe(v)) for k,v in value.items()}
   if isinstance(value,list):return [safe(v) for v in value]
   if isinstance(value,str) and 'voice_approval' in value:
    try:return json.dumps(safe(json.loads(value)),ensure_ascii=False)
    except ValueError:pass
   return value
  data=safe(data)
  row={'at':round(time.monotonic()-start,3),'kind':kind,**data};metrics.append(row)
  print(json.dumps(row,ensure_ascii=False),flush=True)
 js=subprocess.check_output(['node','-e',"const ts=require('./mobile/node_modules/typescript'),fs=require('fs');process.stdout.write(ts.transpileModule(fs.readFileSync('frontend/src/components/voice/live-backend.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)"],cwd=ROOT).decode()
 async with async_playwright() as pw:
  browser=await pw.chromium.launch(headless=True,args=['--autoplay-policy=no-user-gesture-required','--mute-audio'])
  page=await browser.new_page()
  await page.add_init_script('window.legacyVoiceClient='+json.dumps(bool(getattr(args,'legacy_client',False)))+';')
  await page.add_init_script('window.persistTrialTranscript='+json.dumps(bool(getattr(args,'persist_transcripts',False)))+';')
  async def api(route):
   nonlocal sid
   path=route.request.url.split('/api/')[-1];body=route.request.post_data_json or {};t=time.monotonic()
   try:
    if path=='session':
     if args.deployed:
      data=await deployed('session',{'sdp':body['sdp'],'room_id':TEST_ROOM,'chat_title':'Voice acceptance','model':'gpt-live-1'})
      sid=data['session']['id']
      await route.fulfill(json=data);return
     pending='trial-'+str(time.time_ns());voice_live.register(pending,USER,instructions,tools,room_history(rows,budget=60000),room_id=getattr(args,'intake_room',None));voice_live.warm(pending)
     agent=voice_live._sessions[pending]['agent']
     if hasattr(agent,'judge'):
      choose=agent.judge.choose
      async def measured_choose(state,questions):
       result=await choose(state,questions);log('decision',result=result);return result
      agent.judge.choose=measured_choose
     async with httpx.AsyncClient(timeout=50) as client:
      r=await client.post('https://api.openai.com/v1/live/sessions',headers={'Authorization':'Bearer '+settings.OPENAI_API_KEY},json={
       'session':voice_live.session_config(instructions,tools,history),'transport':{'type':'webrtc','sdp':body['sdp']}})
      r.raise_for_status();data=r.json()
     sid=data['session']['id'];voice_live.bind_session(pending,sid)
    elif path=='transcript':
     await ChatService().send_message(TEST_ROOM,USER,'🎙 '+body['text'],sender_type='human' if body['role']=='user' else 'ai')
     data={'ok':True}
    elif path=='backend':await route.continue_();return
    elif path=='steer':
     data=await deployed('backend/steer',{'session_id':sid,'input':body['input']}) if args.deployed else {'accepted':await voice_live.steer(sid,USER,body['input'])}
     log('steer',**data)
    elif path=='jobs':
     data=await args.tool_executor('command_center',{'action':'jobs'}) if getattr(args,'tool_executor',None) else await execute({'action':'jobs'},TEST_ROOM,USER)
    elif path=='tool':
     name=body['name'];a=body['args']
     if getattr(args,'tool_executor',None):data=await args.tool_executor(name,a)
     elif name=='enter_voice_standby':data={'ok':True}
     elif name=='command_center' and a.get('action') in ('search','read','list','overview','status','requests'):data=await execute(a,ROOM,USER)
     elif name=='read_room_history':data={'messages':await ChatService().get_messages(ROOM,USER,limit=min(50,int(a.get('limit',30))))}
     elif name=='check_dan_status':data=await execute({'action':'requests'},TEST_ROOM if 'work' in args.cases.split(',') else ROOM,USER)
     elif name=='delegate_to_dan' and 'work' in args.cases.split(','):
      data=await execute({'action':'work','task':a['task']+f'\n試験用のローカルメモ作成だけを実行。保存先は {(OUT/args.label).as_posix()}。外部送信・購入・公開を行わない。'},TEST_ROOM,USER)
     elif name=='control_dan_task' and 'work' in args.cases.split(',') and a.get('operation')=='update':
      data=await execute({**a,'action':'control_job'},TEST_ROOM,USER)
     else:data={'error':'Read-only test: external actions are disabled.'}
     log('tool',name=name,args=a,seconds=round(time.monotonic()-t,3),bytes=len(json.dumps(data,ensure_ascii=False)))
    else:raise ValueError('Unknown endpoint')
    await route.fulfill(json=data)
   except Exception as e:
    log('error',path=path,error=type(e).__name__)
    await route.fulfill(json={'error':str(e)[:250]},status=500)
  await page.route(trial_origin+'/api/**',api)
  await page.route(trial_origin+'/',lambda r:r.fulfill(body='<html><body>Isolated Dan voice acceptance</body></html>',content_type='text/html'))
  await page.goto(trial_origin+'/')
  job_js=subprocess.check_output(['node','-e',"const ts=require('./mobile/node_modules/typescript'),fs=require('fs');process.stdout.write(ts.transpileModule(fs.readFileSync('frontend/src/components/voice/live-jobs.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)"],cwd=ROOT).decode()
  await page.add_script_tag(content='window.exports={};'+js+job_js+';window.LiveBackend=exports.LiveBackend;window.appendLive=exports.appendLive;window.LiveJobs=exports.LiveJobs;window.liveJobObservation=exports.liveJobObservation;window.readLiveBackendStream=exports.readLiveBackendStream;')
  if args.local_end_gate:
   for filename,export_name in [('call-intent','callIntent'),('call-end-gate','CallEndGate')]:
    compiled=subprocess.check_output(['node','-e',"const ts=require('./mobile/node_modules/typescript'),fs=require('fs');process.stdout.write(ts.transpileModule(fs.readFileSync(process.argv[1],'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)",f'mobile/{filename}.ts'],cwd=ROOT).decode()
    await page.add_script_tag(content='(()=>{const exports={};const require=()=>window.callIntent;'+compiled+f';window.{export_name}='+('exports' if filename=='call-intent' else 'exports.CallEndGate')+';})();')
  await page.expose_function('recordEvent',lambda e:log('live',**e))
  await page.evaluate('(value)=>window.suppressFollowupDelegation=value',args.suppress_followup_delegation)
  try:
   await page.evaluate('''async()=>{
    window.events=[];window.pcm=[];window.dialogue=[];window.buffers={user:'',assistant:''};window.lastSpeech=0;
    const ac=window.ac=new AudioContext({sampleRate:48000});await ac.resume();
    const dest=ac.createMediaStreamDestination();window.dest=dest;
    const silent=ac.createConstantSource();silent.offset.value=0;silent.connect(dest);silent.start();
    const pc=window.pc=new RTCPeerConnection();pc.addTrack(dest.stream.getAudioTracks()[0],dest.stream);
    const endGate=window.CallEndGate ? new window.CallEndGate() : null;
    const closeCall=source=>{if(window.callEnded)return;window.callEnded=true;window.backend?.close();
      pc.close();dest.stream.getTracks().forEach(t=>t.stop());clearInterval(window.endGateTimer);
      recordEvent({type:'call_closed',source,wall:Date.now(),connectionState:pc.connectionState});};
    if(endGate){let measuring=false;window.endGateTimer=setInterval(async()=>{
      if(measuring || window.callEnded)return;measuring=true;
      try{let level=null;const stats=await pc.getStats();stats.forEach(row=>{
        if(row.type==='media-source' && row.kind==='audio' && typeof row.audioLevel==='number')level=row.audioLevel;
      });endGate.microphone(level,Date.now());if(endGate.shouldEnd(Date.now()))closeCall('local_end_gate');}
      finally{measuring=false;}
    },200);}
    pc.ontrack=e=>{
      const stream=e.streams[0]||new MediaStream([e.track]);
      const audio=document.createElement('audio');audio.autoplay=true;audio.srcObject=stream;document.body.appendChild(audio);audio.play();
      const source=ac.createMediaStreamSource(stream),proc=ac.createScriptProcessor(2048,1,1);
      window.outputNodes={source,proc,audio};
      source.connect(proc);proc.connect(ac.destination);
      proc.onaudioprocess=e=>{const d=e.inputBuffer.getChannelData(0);let peak=0;
        for(const x of d)peak=Math.max(peak,Math.abs(x));
        if(peak>.01){window.audioQuiet=false;if(Date.now()-lastSpeech>400)recordEvent({type:'audio_start',wall:Date.now()});lastSpeech=Date.now();if(!window.segmentSpeech)window.segmentSpeech=Date.now();}
        else if(lastSpeech && !window.audioQuiet && Date.now()-lastSpeech>=120){window.audioQuiet=true;recordEvent({type:'audio_end',wall:lastSpeech,detected_wall:Date.now()});}
        window.pcm.push(Array.from(d));};
    };
    const dc=window.dc=pc.createDataChannel('events');
    const request=async(path,body)=>{const r=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error);return d;};
    const send=(kind,text,id=null)=>appendLive(event=>dc.send(JSON.stringify(event)),kind,text,id);
    window.backend=new LiveBackend(async(input,onText)=>readLiveBackendStream(await fetch('/api/backend',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({input})}),onText),
      async(name,args)=>{const result=await request('tool',{name,args});if(result.accepted&&result.receipt?.id){window.awaitedJob=result.receipt.id;window.jobFinished=false;}if(name==='enter_voice_standby'){
        closeCall('backend');
      }return result;},
      (text,id)=>{window.lastFinalAt=Date.now();recordEvent({type:'backend_report',text});send('commentary',text,id.startsWith('followup-')?null:id);},
      error=>{recordEvent({type:'backend_error',error});send('commentary','確認に失敗しました: '+error);},()=>{},
      input=>request('steer',{input}),
      (state,id)=>{recordEvent({type:'work_state',state});window.currentWork=state;});
    let userTurn=0,userLength=0,followupEligible=false,hasActiveJobs=false;
    const jobObservations=new Map();
    const context=()=>[{role:'user',content:JSON.stringify({...(!window.legacyVoiceClient?{utterance_final:!buffers.user}:{}),dialogue:[...dialogue,...Object.entries(buffers).filter(([,text])=>text).map(([role,text])=>({role,text}))]})}];
    const timers={};window.flush=role=>{if(buffers[role]){if(window.legacyVoiceClient||window.persistTrialTranscript)void request('transcript',{role,text:buffers[role]});dialogue.push({role,text:buffers[role]});buffers[role]='';
      if(role==='user' && followupEligible)backend.followupSpeech(userTurn,userLength,context);}};
    dc.onmessage=e=>{const m=JSON.parse(e.data);
      if(m.type.includes('transcript.delta')){
      const role=m.type.includes('input_')?'user':'assistant';
      if(role==='user'){if(!buffers.user){userTurn++;userLength=0;followupEligible=hasActiveJobs;
        if(window.currentWork && window.currentWork.state!=='complete' && (window.currentWork.state!=='executing' || hasActiveJobs))send('thinking',JSON.stringify({current_work:window.currentWork}));
        for(const observation of jobObservations.values())send('thinking',observation);
      }userLength+=(m.delta||'').length;}
      buffers[role]+=m.delta||'';
      if(role==='user')endGate?.transcript(buffers.user,Date.now());
        clearTimeout(timers[role]);timers[role]=setTimeout(()=>flush(role),2500);
        recordEvent({type:m.type,delta:m.delta,start_ms:m.start_ms,end_ms:m.end_ms});
    }else if(m.type==='session.delegation.created'){
      recordEvent({type:m.type,delegation:m.delegation,request:m.request});
      if(window.suppressFollowupDelegation && hasActiveJobs && userTurn>1){recordEvent({type:'simulated_missing_delegation'});return;}
      backend.delegateSpeech(m.delegation.id,userTurn,userLength,()=>[{type:'message',role:'user',content:[{type:'input_text',text:JSON.stringify({current_time:new Date().toISOString(),timezone:'Asia/Tokyo',...(!window.legacyVoiceClient?{utterance_final:!buffers.user}:{}),dialogue:[...dialogue,...Object.entries(buffers).filter(([,t])=>t).map(([role,text])=>({role,text}))],request:m.request})}]}]);
      }else if(m.type==='session.started'){
        window.started=true;send('instructions','現在日時は'+new Date().toLocaleString('ja-JP',{timeZone:'Asia/Tokyo'})+' Asia/Tokyo。');
      }else if(m.type==='error')recordEvent({type:'error',error:m.error});
    };
    await pc.setLocalDescription(await pc.createOffer());
    await new Promise(resolve=>{if(pc.iceGatheringState==='complete')resolve();else{pc.onicegatheringstatechange=()=>{if(pc.iceGatheringState==='complete')resolve();};setTimeout(resolve,5000);}});
    const data=await request('session',{sdp:pc.localDescription.sdp});
    await pc.setRemoteDescription({type:'answer',sdp:data.transport.sdp});
    window.say=async encoded=>{window.segmentSpeech=0;window.lastFinalAt=0;const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
      const src=ac.createBufferSource();src.buffer=await ac.decodeAudioData(bytes.buffer);src.connect(dest);
      await new Promise(resolve=>{src.onended=resolve;src.start();});return Date.now();};
    window.beginJobPolling=()=>{const jobs=new LiveJobs();let polling=false;window.jobTimer=setInterval(async()=>{if(polling)return;polling=true;
      try{const data=await request('jobs',{});hasActiveJobs=(data.jobs||[]).some(j=>!['completed','failed','cancelled'].includes(j.state));for(const {job,event} of jobs.updates(data.jobs||[])){
        const text=JSON.stringify({job_id:job.id,task:job.task,state:job.state,event});
        backend.addInput({type:'message',role:'user',content:[{type:'input_text',text}]});
        recordEvent({type:'job_update',state:job.state,event});
        if(job.state==='running' && !window.jobStartedAt)window.jobStartedAt=Date.now();
         const observation=liveJobObservation(job,event);
         if(observation.kind==='commentary'){jobObservations.delete(job.id);send('commentary',observation.text);}else jobObservations.set(job.id,observation.text);
        if(event.kind==='result'){if(job.id===window.awaitedJob)window.jobFinished=true;window.lastFinalAt=Date.now();}
      }}finally{polling=false;}},1500);};
   }''')
   await page.wait_for_function('window.started',timeout=60000)
   log('connected')
   if 'work' in args.cases.split(',') or getattr(args,'poll_jobs',False):await page.evaluate('beginJobPolling()')
   for name in args.cases.split(','):
    if getattr(args,'before_case',None):await args.before_case(name)
    log('input_start',case=name,text=PHRASES[name]);before=len(metrics)
    ended=await page.evaluate('s=>say(s)',base64.b64encode((OUT/(name+'.wav')).read_bytes()).decode())
    log('input_end',case=name,wall=ended)
    deadline=time.monotonic()+args.wait
    interjected=False
    input_ended=time.monotonic()
    while time.monotonic()<deadline:
     await asyncio.sleep(.3)
     if await page.evaluate('!!window.callEnded'):break
     interject_ready = (name=='reservation' and args.interject in ('status','correction') and time.monotonic()-input_ended>5) or (name=='work' and args.interject=='work_change' and await page.evaluate('window.jobStartedAt && Date.now()-window.jobStartedAt>1500'))
     if args.interject=='interrupt':
      interject_ready=await page.evaluate('window.segmentSpeech && Date.now()-window.segmentSpeech>700 && Date.now()-window.lastSpeech<150')
     if interject_ready and not interjected:
      interjected=True
      log('input_start',case=args.interject,text=PHRASES[args.interject])
      wall=await page.evaluate('s=>say(s)',base64.b64encode((OUT/(args.interject+'.wav')).read_bytes()).decode())
      log('input_end',case=args.interject,wall=wall)
      ended=wall
     # A backchannel during the injected utterance is not its answer. Otherwise
     # we advance immediately at WAV end and interrupt the response we measure.
     if await page.evaluate('end=>window.segmentSpeech && window.lastSpeech>end && Date.now()-window.lastSpeech>6000', ended):
      if await page.evaluate('!!window.awaitedJob && !window.jobFinished'):continue
      # A courtesy acknowledgement is not the answer to a lookup.
      if name=='work':
       if await page.evaluate('window.jobFinished && window.lastSpeech > window.lastFinalAt'):break
      elif (name not in ('reservation','correction') and not name.startswith('real_search')) or await page.evaluate('window.lastFinalAt && window.lastSpeech > window.lastFinalAt'):break
    transport=await page.evaluate('''async()=>{
      if(pc.signalingState==='closed')return {rows:[],closed:true};
      const fields=['type','kind','mediaType','audioLevel','packetsReceived','packetsLost','jitter',
        'jitterBufferDelay','jitterBufferEmittedCount','concealedSamples','silentConcealedSamples','totalSamplesReceived',
        'totalAudioEnergy','totalSamplesDuration','roundTripTime','totalRoundTripTime','roundTripTimeMeasurements'];
      const rows=[];(await pc.getStats()).forEach(r=>{
        if((r.kind==='audio'||r.mediaType==='audio')&&['media-source','inbound-rtp','remote-inbound-rtp'].includes(r.type)){
          const row={};for(const k of fields)if(r[k]!==undefined)row[k]=r[k];rows.push(row);
        }
      });return {rows,baseLatency:ac.baseLatency,outputLatency:ac.outputLatency};
    }''')
    log('transport_snapshot',case=name,**transport)
    log('case_end',case=name)
    if await page.evaluate('!!window.callEnded'):break
   await page.evaluate('clearInterval(window.jobTimer);clearInterval(window.endGateTimer);backend.close();pc.close();')
   encoded=await page.evaluate('''()=>{const count=pcm.reduce((n,c)=>n+c.length,0),buf=new ArrayBuffer(count*2),view=new DataView(buf);let at=0;
     for(const c of pcm)for(const x of c){view.setInt16(at,Math.max(-32768,Math.min(32767,Math.round(x*32767))),true);at+=2;}
     const bytes=new Uint8Array(buf),parts=[];for(let i=0;i<bytes.length;i+=8192)parts.push(String.fromCharCode(...bytes.subarray(i,i+8192)));
     return btoa(parts.join(''));}''')
   import wave
   with wave.open(str(OUT/(args.label+'.wav')),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(48000);f.writeframes(base64.b64decode(encoded))
  finally:
   if sid and args.deployed:
    try:await deployed('backend/close',{'session_id':sid})
    except Exception as exc:log('close_error',error=type(exc).__name__)
   if sid and sid in voice_live._sessions:voice_live.close(sid,USER)
   await browser.close()
   server.should_exit=True
   await server_task
   (OUT/(args.label+'.json')).write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--cases',default='date,smalltalk,reservation,repeat');parser.add_argument('--wait',type=int,default=40);parser.add_argument('--label',default='trial');parser.add_argument('--interject',choices=['status','correction','work_change']);parser.add_argument('--deployed');parser.add_argument('--suppress-followup-delegation',action='store_true');parser.add_argument('--speech-instructions');parser.add_argument('--local-end-gate',action='store_true')
 asyncio.run(run(parser.parse_args()))
