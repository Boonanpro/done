const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function runtime(){
 const events=[],sent=[],calls=[],elements={};let now=100000;
 const box={structuredClone,performance,TextEncoder,crypto:require('node:crypto').webcrypto,Date:class extends Date{static now(){return now;}},setTimeout,clearTimeout,
 context:{room_id:'room',content_id:'A',playhead:10,selected:[]},dc:{readyState:'open'},epoch:0,reasonRunning:false,
 audit:[],conversationMemory:[],activeNotice:null,waitingForUser:false,audioPlaying:false,
 api:async()=>({available:true,handled:false,action:'execute',needs_backend:true}),
 record:(type,data)=>events.push({type,...data}),send:e=>sent.push(e),message:()=>({textContent:''}),saveConversation:()=>{},
 flushAudit:async()=>{},begin:async c=>{calls.push(c);return {context:c};},runReasoning:async()=>{},setBusy:()=>{},error:e=>{throw e;},
 window:{},busy:true,active:true,LIVE_VOICE:true,pendingQuestion:{id:'question'},presentationId:null,targetTurn:'target',previousTurn:'previous',pendingNewId:null,
 $:id=>elements[id]||(elements[id]={}),target:()=>{},restoreConversation:()=>{},startingVoice:false,
 interrupt:()=>{throw Error('Browsing must not cancel work');},resetPresentationFeed:()=>{},document:{body:{classList:{remove:()=>{}}}}};
 vm.createContext(box);vm.runInContext(fs.readFileSync('app/static/editor-live.js','utf8'),box);
 const assistant=fs.readFileSync('app/static/editor-assistant.js','utf8');
 vm.runInContext(assistant.slice(assistant.indexOf('window.__updateEditorContext='),assistant.indexOf('window.__editorAck=')),box);
 vm.runInContext('liveConnection={started:true,startedAt:100000,id:"session",editContext:structuredClone(context),rows:{},views:[]};liveObserve(context)',box);
 return {box,events,sent,calls,at:t=>now=100000+t,run:s=>vm.runInContext(s,box)};
}

test('native Responses tools return all results once and retain their original project',async()=>{
 const r=runtime(),executed=[];
 r.box.executeLiveConsultationTool=async(item,session,captured)=>{executed.push([item.call_id,captured.content_id]);return {saved:true};};
 await r.run(`handleLiveResponseEvent({delegation_id:'d',event:{type:'response.created'}},liveConnection)`);
 r.box.context.content_id='B';
 for(const id of ['one','two','one'])await r.run(`handleLiveResponseEvent({delegation_id:'d',event:{type:'response.output_item.done',item:{type:'function_call',name:'update_consultation_sheet',call_id:'${id}',arguments:'{}'}}},liveConnection)`);
 await r.run(`handleLiveResponseEvent({delegation_id:'d',event:{type:'response.completed'}},liveConnection)`);
 assert.deepEqual(executed,[['one','A'],['two','A']]);
 assert.equal(r.sent.filter(e=>e.type==='response.item.create').length,2);
 assert.equal(r.sent.filter(e=>e.type==='response.create').length,1);
});

test('failed reference classification completes the handoff without launching Astra',async()=>{
 for(const failure of ['503','network']){
  const r=runtime();r.box.presentationFeed=new Map();
  r.run('liveConnection.rows.user={id:"u",text:"show some examples"}');
  r.box.api=async()=>{if(failure==='network')throw Error('network');return {available:false,handled:false,needs_backend:false,failure:{http_status:503}};};
  await r.run('liveDelegate({delegation:{id:"failed"}},liveConnection);liveTaskQueue');
  assert.equal(r.calls.length,0);
  assert.equal(r.events.find(e=>e.type==='reference_lookup_failed').continued_to_backend,false);
  assert.ok(r.sent.some(e=>e.type==='session.commentary.append'&&JSON.parse(e.content).kind==='reference_lookup_failed'));
 }
});

test('streaming acknowledgement reuses the user decision but new user feedback does not',async()=>{
 const r=runtime();let requests=0;
 r.box.api=async()=>{requests++;return {available:true,handled:true,action:'compare'};};
 r.run('liveConnection.rows.user={id:"u",text:"a film"}');
 await r.run('visualDecision(liveConnection,[{role:"user",text:"a film"}],[])');
 await r.run('visualDecision(liveConnection,[{role:"user",text:"a film"},{role:"assistant",text:"Let me find"}],[])');
 assert.equal(requests,1);
 await r.run('visualDecision(liveConnection,[{role:"user",text:"a film"},{role:"assistant",text:"Let me find examples"},{role:"user",text:"more intimate"}],[])');
 assert.equal(requests,2);
});

test('unshown references reach the next decision, stay scoped, and are discarded on cancellation',async()=>{
 const r=runtime(),requests=[];
 r.box.api=async(path,body)=>{requests.push(body);return requests.length===1?
  {available:true,handled:true,action:'compare',selected_library_ids:['film']}:
  {available:true,handled:true,action:'talk',pending_disposition:'discard'};};
 r.run('liveConnection.rows.user={id:"u",text:"show a film"}');
 await r.run('visualDecision(liveConnection,[{role:"user",text:"show a film"}],[])');
 r.run('liveConnection.rows.user={id:"next",text:"cancel"}');
 await r.run('visualDecision(liveConnection,[{role:"user",text:"show a film"},{role:"user",text:"cancel"}],[])');
 assert.equal(requests[1].pending_reference.ids[0],'film');
 assert.equal(r.run('liveConnection.pendingReference'),null);
 r.run('liveConnection.pendingReference={room:"other",content:"A",text:"old",ids:["old"]}');
 await r.run('visualDecision(liveConnection,[{role:"user",text:"different room"}],[])');
 assert.equal(requests[2].pending_reference,null);
});

test('finished conversational handoff reports that no search is running',async()=>{
 const r=runtime();r.box.api=async()=>({available:true,handled:true,action:'talk'});
 await r.run('liveDelegate({delegation:{id:"status"}},liveConnection);liveTaskQueue');
 const result=r.sent.filter(e=>e.type==='session.commentary.append').map(e=>JSON.parse(e.content)).find(e=>e.kind==='conversation_action');
 assert.equal(result.reference_search_running,false);
 assert.equal(result.executed,false);
});

test('job snapshots remain silent and do not equate an idle reply with a stopped job',()=>{
 const r=runtime();
 r.run('liveProductionFacts={room_id:"room",content_id:"A",observed_at_ms:100000,active:[{id:"job",status:"running",request:"render"}],recent:[]};liveConnection.work={status:"idle"};sendExecutionFacts()');
 const facts=r.sent.map(e=>{assert.equal(e.type,'session.thinking.append');return JSON.parse(e.content);});
 assert.equal(facts[0].active_count,1);assert.equal(facts[0].conversation_status,'idle');
 assert.equal(facts[1].status,'running');
 r.run('liveProductionFacts.content_id="B"');assert.equal(r.run('liveFacts().production'),null);
});

test('delegation reuses the same reference set even when order changes',async()=>{
 const r=runtime();r.box.presentationFeed=new Map();
 r.run('liveConnection.rows.user={id:"u",text:"both are good"};livePresentationFacts={id:"shown",room_id:"room",content_id:"A",items:[{library_id:"a"},{library_id:"b"}]}');
 r.box.api=async path=>{assert.equal(path,'/visual-decision');return {available:true,handled:true,action:'compare',selected_library_ids:['b','a']};};
 await r.run('liveDelegate({delegation:{id:"same"}},liveConnection);liveTaskQueue');
 assert.equal(r.calls.length,0);assert.ok(r.events.some(e=>e.type==='reference_library_reused'));
});

test('discovery evidence is silent, complete JSON and labels reused references honestly',()=>{
 const r=runtime();
 r.box.discovery={change:'pivot',next_axis:'medium',axis_label:'映像の表現',beliefs:{tone:{preferred:'calm',avoid:null}},
   comparison:{reason:'evidenced_contrast',sides:[{id:'old',label:'実写'}]},reused_ids:['old']};
 r.run('sendDiscoveryFacts(discovery,null,[{library_id:"old"}])');
 assert.ok(r.sent.length>=3);
 const values=r.sent.map(e=>{assert.equal(e.type,'session.thinking.append');return JSON.parse(e.content);});
 assert.equal(values.find(v=>v.kind==='comparison_evidence').reused,true);
 assert.equal(values.find(v=>v.kind==='current_preference').preferred,'calm');
});

test('requested references become perceptible during speech, before spoken report is allowed',()=>{
 const r=runtime();r.box.audioPlaying=true;
 r.run('liveConnection.rows.user={id:"u",text:"show references"};liveConnection.visualPresented={text:"show references"};livePresented({context,turn_id:"t",liveDelegation:"d",referenceOperation:"selected_existing_library_examples_without_modification"},{id:"p",items:[{id:"one",title:"Only one",kind:"video"}]},{ok:true})');
 const summary=r.sent.filter(e=>e.type==='session.thinking.append').map(e=>JSON.parse(e.content)).find(e=>e.kind==='current_reference_comparison');
 assert.equal(summary.count,1);
 assert.equal(r.sent.filter(e=>e.type==='session.commentary.append').length,0);
 r.box.audioPlaying=false;
 r.run('flushReferenceReport(liveConnection)');
 assert.equal(r.sent.filter(e=>e.type==='session.commentary.append').length,0);
 r.run('clearTimeout(liveConnection.referenceReportTimer)');
});

test('reference identities unify duplicate visuals but preserve an edited variant',()=>{
 const r=runtime();
 const original={id:'old',library_id:'caption',kind:'composition',composition:{layers:[{text:'hello',fontSize:40}]}};
 r.box.presentationFeed=new Map([['a',{id:'a',at:1,items:[original]}],['b',{id:'b',at:2,items:[{...original,id:'copy'},{...original,id:'revision',composition:{layers:[{text:'hello',fontSize:80}]}}]}]]);
 const items=r.run('referenceDecisionItems()');
 assert.equal(items[0].reference_identity,items[1].reference_identity);
 assert.notEqual(items[0].reference_identity,items[2].reference_identity);
 assert.equal(items[1].position,1);assert.equal(items[2].position,2);
 assert.equal(items[0].is_latest,false);assert.equal(items[1].is_latest,true);
});

test('Jev view action applies once and skips Astra; unsupported media falls back',async()=>{
 const r=runtime();let applied=0;
 Object.assign(r.box,{CSS:{escape:s=>s},presentationFeed:new Map([['p',{id:'p',at:1,items:[{id:'i',title:'image',kind:'image'}]}]]),
  api:async()=>({handled:true,action:'reveal',item_id:'i'}),document:{body:{classList:{add:()=>{}}}}});
 r.box.$('reference-cards').querySelector=()=>({scrollIntoView:()=>applied++,querySelector:()=>null});
 await r.run('liveDelegate({delegation:{id:"fast"}},liveConnection);liveTaskQueue');
 assert.equal(applied,1);assert.equal(r.calls.length,0);
 assert.ok(r.sent.map(x=>x.content).join('').includes('presentation_action_completed'));
 r.box.api=async()=>({handled:true,action:'play',item_id:'i'});
 await r.run('liveDelegate({delegation:{id:"unsupported"}},liveConnection);liveTaskQueue');
 assert.equal(r.calls.length,1);
});

test('long result invites speech once instead of once per fragment',()=>{
 const r=runtime();r.run('liveAppend("commentary","あ".repeat(500),null)');
 assert.equal(r.sent.filter(e=>e.type==='session.commentary.append').length,1);
 assert.ok(r.sent.filter(e=>e.type==='session.thinking.append').length>0);
 assert.equal(r.sent.map(e=>e.content).join(''),'あ'.repeat(500));
});

test('same words share a visual decision despite changing view traces; changed words or focus do not',async()=>{
 const r=runtime();let calls=0;r.box.api=async()=>{calls++;return {handled:true};};
 r.run('liveConnection.rows.user={id:"u"};');
 await r.run('visualDecision(liveConnection,[{role:"user",text:"quiet",observed_views:[1]}],[])');
 await r.run('visualDecision(liveConnection,[{role:"user",text:"quiet",observed_views:[2]}],[])');
 assert.equal(calls,1);
 await r.run('visualDecision(liveConnection,[{role:"user",text:"not quiet"}],[])');
 assert.equal(calls,2);
 r.box.referenceFocus={item_id:'new'};
 await r.run('visualDecision(liveConnection,[{role:"user",text:"not quiet"}],[])');
 assert.equal(calls,3);
});

test('speculative references are inspectable but not pushed as a completed answer',()=>{
 const r=runtime();
 r.run('livePresented({turn_id:"preview",context,liveSession:liveConnection,livePreview:true},{id:"p",items:[{id:"i",title:"look",kind:"video"}]},{ok:true})');
 assert.equal(r.sent.filter(e=>e.type==='session.commentary.append').length,0);
 assert.equal(r.sent.length,0);
 assert.equal(r.run('liveFacts().presentation.id'),'p');
});

test('existing speculative references update perception without requesting speech',()=>{
 const r=runtime();
 r.run('livePresented({turn_id:"preview",context,liveSession:liveConnection,livePreview:true,referenceOperation:"selected_existing_library_examples_without_modification"},{id:"p",items:[{id:"i",title:"look",kind:"video",note:"Actual silent footage"}]},{ok:true})');
 assert.ok(r.sent.some(e=>e.content.includes('current_reference_comparison')));
 assert.ok(r.sent.every(e=>e.type==='session.thinking.append'));
 assert.equal(r.run('liveConnection.referenceReport'),undefined);
});

test('requested references reach Live during speech without requesting a new speaking turn',()=>{
 const r=runtime();r.box.audioPlaying=true;
 r.run('livePresented({turn_id:"requested",context,liveSession:liveConnection},{id:"new",items:[{id:"i",title:"look",kind:"video"}]},{ok:true})');
 assert.ok(r.sent.some(e=>e.type==='session.thinking.append'&&e.content.includes('presentation_available')));
 assert.equal(r.sent.filter(e=>e.type==='session.commentary.append').length,0);
});

test('a real delegation after speculative display reports it without a second tool execution',async()=>{
 const r=runtime();
 r.run('liveConnection.rows.user={id:"u",text:"that look"};liveConnection.visualPresented={id:"u",text:"that look"};livePresentationFacts={id:"p",display:{ok:true},items:[]}');
 await r.run('liveDelegate({delegation:{id:"actual"}},liveConnection);liveTaskQueue');
 assert.equal(r.calls.length,0);
 assert.ok(r.sent.some(e=>e.type==='session.commentary.append'&&e.content.includes('presentation_available')));
});

test('reference speech waits for delayed input words and reports only the latest comparison once',()=>{
 const r=runtime();r.box.setTimeout=()=>1;
 r.run('liveConnection.rows.user={id:"u",end:9000,text:"not finished"};liveConnection.lastInputSound=100000;liveConnection.inputTranscriptOffset=90000;liveConnection.lastVisualTranscriptAt=100000;livePresentationFacts={id:"p",revision:1};queueReferenceReport({},livePresentationFacts,liveConnection)');
 r.at(2000);r.run('flushReferenceReport(liveConnection)');
 assert.equal(r.sent.length,0);
 r.run('livePresentationFacts={id:"p",revision:2};queueReferenceReport({},livePresentationFacts,liveConnection);liveConnection.rows.user.end=10050;flushReferenceReport(liveConnection)');
 assert.equal(r.sent.filter(e=>e.type==='session.commentary.append').length,1);
 assert.ok(r.sent.at(-1).content.includes('"revision":2'));
 r.run('queueReferenceReport({},livePresentationFacts,liveConnection)');
 assert.equal(r.sent.filter(e=>e.type==='session.commentary.append').length,1);
});

test('a late sentence ending invalidates the queued explanation without delaying the visual',()=>{
 const r=runtime();r.box.setTimeout=()=>1;
 r.run('liveConnection.rows.user={id:"u",text:"make it flash"};liveConnection.lastVisualTranscriptAt=100000;liveConnection.visualPresented={id:"u",text:"make it flash"};livePresentationFacts={id:"p",revision:1,items:[]};queueReferenceReport({},livePresentationFacts,liveConnection)');
 r.at(450);r.run('flushReferenceReport(liveConnection)');
 assert.equal(r.sent.length,0);
 r.run('liveConnection.rows.user.text="do not make it flash";liveConnection.lastVisualTranscriptAt=100450');
 r.at(1200);r.run('flushReferenceReport(liveConnection)');
 assert.equal(r.sent.length,0);
 assert.equal(r.run('liveConnection.referenceReport'),null);
 r.run('liveConnection.visualPresented.text=liveConnection.rows.user.text;livePresentationFacts={id:"p",revision:2,items:[]};queueReferenceReport({},livePresentationFacts,liveConnection)');
 assert.equal(r.sent.filter(e=>e.type==='session.commentary.append').length,1);
 assert.equal(JSON.parse(r.sent.at(-1).content).revision,2);
});

test('reference display bypasses editing setup and reports a rendered frame despite trailing transcript',async()=>{
 const r=runtime();r.box.presentationFeed=new Map();let rendered=0;
 r.box.api=async path=>path==='/visual-decision'
  ?{handled:true,action:'compare',selected_library_ids:['a'],elapsed_ms:240}
  :{presentation:{id:'p',revision:1,items:[{id:'i',kind:'image',library_id:'a'}]}};
 r.box.renderReferences=()=>rendered++;
 r.box.presentationReady=async()=>{r.run('liveConnection.rows.user.text+="、かな"');return {ok:true};};
 r.box.setTimeout=()=>1;
 r.run('liveConnection.rows.user={id:"u",text:"参考を見せて"};liveDelegate({delegation:{id:"display"}},liveConnection)');
 await r.run('liveTaskQueue');
 assert.equal(r.calls.length,0);assert.equal(rendered,1);
 assert.ok(r.events.some(e=>e.type==='reference_library_displayed'&&e.ok));
 assert.equal(r.run('liveFacts().presentation.id'),'p');
 assert.ok(!r.events.some(e=>e.type==='live_backend_started'));
});

test('transcript changing during reference lookup still executes the request',async()=>{
 const r=runtime();r.box.presentationFeed=new Map();let finish,entered,lookups=0;
 const ready=new Promise(resolve=>entered=resolve);
 r.box.api=async path=>{if(path==='/visual-decision'){if(lookups++)return {handled:false,action:'execute'};entered();return new Promise(resolve=>finish=resolve);}return {handled:false};};
 r.run('liveConnection.rows.user={id:"u",text:"show storyboard"};conversationMemory.push({role:"user",text:"show storyboard"});liveDelegate({delegation:{id:"delta"}},liveConnection)');
 await ready;
 r.run('liveConnection.rows.user.text+=" please";conversationMemory[0].text+=" please"');
 finish({handled:true,selected_library_ids:['old']});await r.run('liveTaskQueue');
 assert.equal(r.calls.length,1);assert.equal(r.calls[0].live_dialogue[0].text,'show storyboard please');
 assert.ok(r.events.some(e=>e.type==='live_backend_started'));
});

test('empty library falls through to production tools rather than abandoning request',async()=>{
 const r=runtime();r.box.presentationFeed=new Map();
 r.box.api=async()=>({handled:true,selected_library_ids:[]});
 await r.run('liveDelegate({delegation:{id:"empty"}},liveConnection);liveTaskQueue');
 assert.equal(r.calls.length,1);assert.ok(r.events.some(e=>e.type==='live_backend_started'));
});

test('another timeline in same room cannot announce its result in this call',()=>{
 const r=runtime();r.run('liveBackendMessage({context:{room_id:"room",content_id:"B"}},{id:"other",text:"old movie finished"})');
 assert.equal(r.sent.length,0);
 assert.equal(r.run('liveDeferredReports[0].content_id'),'B');
});

test('Jev late answer cannot operate another project or a revised utterance',async()=>{
 const r=runtime();let applied=0;
 Object.assign(r.box,{CSS:{escape:s=>s},presentationFeed:new Map([['p',{at:1,items:[{id:'i',title:'A'}]}]]),
 document:{body:{classList:{add:()=>{}}}},api:async()=>{r.box.context.content_id='B';return {handled:true,action:'reveal',item_id:'i'};}});
 r.box.$('reference-cards').querySelector=()=>({scrollIntoView:()=>applied++,querySelector:()=>null});
 const result=await r.run('livePresentationAction({...context,live_dialogue:[]},liveConnection,"d",()=>true)');
 assert.equal(result,false);assert.equal(applied,0);
 r.box.api=async()=>{r.run('liveConnection.rows.user={id:"new",text:"やっぱり違う"}');return {handled:true,action:'reveal',item_id:'i'};};
 assert.equal(await r.run('livePresentationAction({...context,live_dialogue:[]},liveConnection,"d",()=>true)'),false);
 assert.equal(applied,0);
});
test('late transcript retains scene A; reference navigation does not cancel or retarget',async()=>{
 const r=runtime();r.at(3500);
 r.run('window.__updateEditorContext({room_id:"room",content_id:"B",playhead:75,selected:[]})');
 r.at(6000);
 r.run('liveTranscript({type:"session.input_transcript.delta",start_ms:500,end_ms:3000,delta:"この文字を大きく"},liveConnection)');
 const views=r.box.audit[0].observed_views;
 assert.equal(views.length,1);assert.equal(views[0].view.content_id,'A');assert.equal(views[0].view.playhead,10);
 assert.equal(r.box.pendingQuestion.id,'question');assert.equal(r.box.previousTurn,'previous');
 r.at(6400); // The utterance has reached the quiet boundary.
 await r.run('liveDelegate({delegation:{id:"d1"}},liveConnection);liveTaskQueue');
 assert.equal(r.calls.length,1);assert.equal(r.calls[0].content_id,'A');assert.equal(r.calls[0].playhead,10);
 assert.equal(r.calls[0].viewed_context.content_id,'B');
 assert.deepEqual(r.events.filter(e=>e.type==='live_work_state').map(e=>e.status),['running','running','idle']);
});
test('one utterance spanning A and B retains both, library is marked invisible',()=>{
 const r=runtime();r.at(1000);r.run('window.__updateEditorContext({room_id:"room",content_id:"B",playhead:80,selected:[]})');
 r.at(2000);r.run('window.__updateEditorContext({room_id:"room",content_id:null})');
 r.at(4000);r.run('liveTranscript({type:"session.input_transcript.delta",start_ms:100,end_ms:3000,delta:"ここと、次のここ"},liveConnection)');
 const views=r.box.audit[0].observed_views;
 assert.deepEqual(Array.from(views,v=>v.view.content_id),['A','B','B']);
 assert.equal(views[2].view.editor_visible,false);
});

test('work updates stay silent while current facts remain readable',()=>{
 const r=runtime();
 r.run('liveWorkState("running","search");liveWorkState("idle");');
 assert.ok(r.sent.every(e=>e.type==='session.thinking.append'));
 assert.equal(r.run('liveFacts().conversation_work.status'),'idle');
 r.run('liveProductionFacts={room_id:"other",active:[{id:"private"}]};livePresentationFacts={room_id:"other",id:"private"}');
 assert.equal(r.run('liveFacts().production'),null);
 assert.equal(r.run('liveFacts().presentation'),null);
 r.run('livePresentationFacts={room_id:"room",content_id:"B",id:"another-timeline"}');
 assert.equal(r.run('liveFacts().presentation'),null);
});

test('presentation delivered outside an active reasoning turn reports immediately once',()=>{
 const r=runtime();
 r.run('turn={context,liveSession:liveConnection,liveDelegation:"d"};window.p={id:"p",items:[{id:"i",kind:"video",title:"3D",note:"Compare movement; footage unverified"}]};livePresented(turn,window.p);livePresented(turn,window.p)');
 const text=r.sent.map(e=>e.content).join('');
 assert.ok(text.includes('3D'));
 assert.equal(r.run('liveFacts().presentation.items[0].note'),'Compare movement; footage unverified');
 assert.ok(r.sent.every(e=>e.delegation_id==='d'));
 assert.equal(r.events.filter(e=>e.type==='live_presentation_delivered').length,1);
 assert.equal(r.run('liveFacts().presentation.id'),'p');
});

test('successive visible refinements in one turn invite one final spoken report',()=>{
 const r=runtime();r.box.reasonRunning=true;
 r.run('turn={context,turn_id:"t",liveSession:liveConnection,liveDelegation:"d"};livePresented(turn,{id:"p1",items:[{id:"i1",kind:"text",title:"First"}]},{ok:true});livePresented(turn,{id:"p2",items:[{id:"i2",kind:"text",title:"Refined"}]},{ok:true});');
 assert.equal(r.sent.length,0);
 assert.equal(r.run('liveFacts().presentation.id'),'p2');
 r.box.reasonRunning=false;r.run('flushPresentationReports()');
 assert.equal(r.sent.filter(e=>e.type==='session.commentary.append').length,1);
 assert.ok(r.sent.map(e=>e.content).join('').includes('Refined'));
 assert.ok(!r.sent.map(e=>e.content).join('').includes('First'));
});

test('display report is spoken once while subsequent backend explanation stays available',()=>{
 const r=runtime();
 r.run('turn={context,liveSession:liveConnection,liveDelegation:"d"};livePresented(turn,{id:"p",items:[{id:"i",kind:"text",title:"A"}]},{ok:true});');
 const before=r.sent.length;
 r.run('liveBackendMessage(turn,{id:"done",phase:"final_answer",text:"The sample was updated."});');
 assert.ok(r.sent.slice(before).every(e=>e.type==='session.thinking.append'));
 assert.ok(r.sent.slice(before).map(e=>e.content).join('').includes('sample was updated'));
});

test('voice receives actual text appearance rather than only a proposal title',()=>{
 const r=runtime();
 const item=r.run('livePresentationItem({id:"i",title:"Quiet",kind:"composition",composition:{background:"#eee9e2",duration:9,layers:[{type:"text",text:"Hello",color:"#48433e",fontSize:44}]}})');
 assert.equal(item.appearance.text_colors[0],'#48433e');
 assert.equal(item.appearance.background,'#eee9e2');
 assert.equal(item.appearance.text[0],'Hello');
});

test('a result updates perception immediately and invites speech once after current speech ends',()=>{
 const r=runtime();r.box.audioPlaying=true;
 r.run('turn={context,turn_id:"t",liveSession:liveConnection,liveDelegation:"d"};livePresented(turn,{id:"p",items:[{id:"i",kind:"text",title:"A"}]},{ok:true});liveBackendMessage(turn,{id:"done",phase:"final_answer",text:"Changed."});');
 assert.equal(r.sent.filter(e=>e.type==='session.commentary.append').length,0);
 assert.ok(r.sent.some(e=>e.type==='session.thinking.append'));
 r.box.audioPlaying=false;r.run('flushPresentationReports();');
 assert.ok(r.sent.some(e=>e.type==='session.commentary.append'));
 const count=r.sent.length;r.run('flushPresentationReports();');assert.equal(r.sent.length,count);
});

test('complete backend message reaches Live before turn ends and is not replayed at completion',async()=>{
 const r=runtime();let release;const pending=new Promise(resolve=>release=resolve);let reads=0;
 Object.assign(r.box,{AbortController,TextDecoder,TextEncoder,reasonController:null,answer:null,reasoningProgress:null,notificationsPaused:false,
  state:()=>{},token:async()=>'',base:'/editor',queueSpeech:()=>{},pumpSpeech:()=>{},fetch:async()=>({ok:true,body:{getReader:()=>({read:async()=>{
   if(reads++===0)return {done:false,value:new TextEncoder().encode(JSON.stringify({type:'text',delta:'A useful answer.'})+'\n'+JSON.stringify({type:'message_complete',id:'m',phase:'final_answer',text:'A useful answer.'})+'\n')};
   await pending;return {done:true,value:new TextEncoder().encode(JSON.stringify({type:'done',has_tools:false})+'\n')};
  }})}})});
 r.run('turn={context,turn_id:"t",liveSession:liveConnection,liveDelegation:"d"};');
 const source=fs.readFileSync('app/static/editor-assistant.js','utf8');
 r.run(source.slice(source.indexOf('async function runReasoning(){'),source.indexOf('async function connect(){')));
 const running=r.run('runReasoning()');await new Promise(resolve=>setImmediate(resolve));
 assert.equal(r.box.reasonRunning,true);
 assert.ok(r.sent.some(e=>e.type==='session.commentary.append'&&e.content.includes('A useful answer.')));
 const count=r.sent.length;release();await running;
 assert.equal(r.sent.length,count);assert.equal(r.box.reasonRunning,false);
});

test('continued delegation steers the active turn without canceling search or starting again',async()=>{
 const r=runtime();const requests=[];
 r.box.api=async(path,body)=>{requests.push({path,body});return {ok:true};};
 r.box.cancelTurn=()=>{throw Error('Must preserve running search');};
 r.run('reasonRunning=true;turn={turn_id:"active",context,liveSession:liveConnection};liveConnection.rows.user={id:"u",text:"その案の雰囲気を聞いています",views:[]}');
 await r.run('liveDelegate({delegation:{id:"continued"}},liveConnection)');
 assert.equal(r.calls.length,0);
 assert.equal(requests.length,1);assert.equal(requests[0].path,'/steer');
 assert.equal(requests[0].body.args.text,'その案の雰囲気を聞いています');
 assert.equal(r.run('turn.liveDelegation'),'continued');
 assert.equal(r.events.filter(e=>e.type==='live_work_state').length,0);
});

test('delegation sends complete original text without waiting for diagnostic uploads',async()=>{
 const r=runtime();r.box.flushAudit=()=>{throw Error('telemetry must not be required');};
 r.at(25000);
 r.run('liveTranscript({type:"session.input_transcript.delta",start_ms:500,end_ms:20000,delta:"左上を固定して背景ごと80％に縮小してください"},liveConnection)');
 r.at(25400);
 await r.run('liveDelegate({delegation:{id:"full-text"}},liveConnection);liveTaskQueue');
 assert.equal(r.calls[0].live_dialogue.at(-1).text,'左上を固定して背景ごと80％に縮小してください');
});

test('library result after a revised utterance never renders or reports stale examples',async()=>{
 const r=runtime();let finishTool,entered;const ready=new Promise(resolve=>entered=resolve);let rendered=0;
 r.box.presentationFeed=new Map();r.box.renderReferences=()=>rendered++;
 r.box.api=async path=>{
  if(path==='/visual-decision')return {handled:true,reference_confidence:1,selected_library_ids:['a']};
  if(path==='/reference-library/present'){entered();return await new Promise(resolve=>finishTool=resolve);}
  return {handled:false};
 };
 r.run('liveConnection.rows.user={id:"u",text:"参考を見せて"};liveDelegate({delegation:{id:"library"}},liveConnection)');
 await ready;
 r.run('liveConnection.rows.user.text="やっぱり別の話です"');
 finishTool({presentation:{id:'old',items:[{id:'a',kind:'image'}]}});
 await r.run('liveTaskQueue');
 assert.equal(rendered,0);
 assert.ok(!r.events.some(e=>e.type==='reference_library_displayed'));
});

test('new delegated request interrupts obsolete reasoning without stopping production',async()=>{
 const r=runtime();let started;const ready=new Promise(resolve=>started=resolve);let runs=0,canceled=[];
 r.box.cancelTurn=async b=>{canceled.push(b.turn_id);return {ok:true};};
 r.box.runReasoning=()=>{
   if(++runs>1){r.box.reasonRunning=false;return Promise.resolve();}
   r.box.turn={turn_id:'old',context:r.box.context};r.box.reasonRunning=true;
   return new Promise((resolve,reject)=>{r.box.reasonController={abort:()=>{const e=Error('aborted');e.name='AbortError';reject(e);}};started();});
 };
 r.run('liveDelegate({delegation:{id:"old"}},liveConnection)');await ready;
 await r.run('liveDelegate({delegation:{id:"new"}},liveConnection);liveTaskQueue');
 assert.equal(runs,2);assert.deepEqual(canceled,['old']);
 assert.ok(!r.events.some(e=>e.type==='live_work_state'&&e.status==='failed'));
 assert.ok(r.events.some(e=>e.type==='live_reasoning_superseded'));
});
test('failed work ends in failed state and is reported to the voice model',async()=>{
 const r=runtime();r.box.runReasoning=async()=>{throw Error('test failure');};r.box.error=()=>{};
 await r.run('liveDelegate({delegation:{id:"fail"}},liveConnection);liveTaskQueue');
 assert.deepEqual(r.events.filter(e=>e.type==='live_work_state').map(e=>e.status),['running','running','failed']);
 assert.ok(r.sent.some(e=>e.type==='session.commentary.append'&&e.content.includes('test failure')));
});

test('microphone pause closes billable transport without dropping queued work',async()=>{
 const r=runtime();let closed=0;
 r.box.pc={close:()=>closed++};r.box.audio={pause:()=>{},srcObject:{}};
 r.box.mic={getTracks:()=>[{enabled:true,stop:()=>{}}]};r.box.clearInterval=clearInterval;
 r.box.dc.close=()=>{};r.box.dc.send=s=>r.sent.push(JSON.parse(s));r.box.completionNotices=[];r.box.audioPlaying=true;
 r.run('liveDelegate({delegation:{id:"before-pause"}},liveConnection);window.oldSession=liveConnection;pauseLive()');
 assert.ok(r.sent.some(e=>e.type==='session.close'));
 assert.equal(r.run('liveConnection'),null);
 assert.equal(r.run('liveEditingContext().content_id'),'A');
 r.run('window.oldSession.finalize()');
 assert.equal(closed,1);assert.equal(r.run('liveClosing'),null);
 await r.run('liveTaskQueue');
 assert.equal(r.calls.length,1);
 assert.equal(r.calls[0].content_id,'A');
});

test('automatic callback enables microphone and waits 30 seconds after speech; explicit close disables callback',async()=>{
 const r=runtime();Object.assign(r.box,{micOn:false,noticeRetryAt:0,notificationsPaused:false,reasonRunning:false,currentWorkLine:'',audioPlaying:false,busy:false,active:false,
  completionNotices:[{room_id:'room',content_id:'A',job_id:'done',status:'done'}],endTone:()=>{},showToast:()=>{},error:()=>{}});
 r.run('livePausedContext=structuredClone(context);liveConnection=null');
 let toggles=0;
 r.box.toggleMic=async()=>{toggles++;r.box.micOn=!r.box.micOn;if(r.box.micOn)r.run('liveConnection={started:true,editContext:structuredClone(context)}');};
 await r.run('announceLiveCompletion()');
 assert.equal(toggles,1);assert.equal(r.box.micOn,true);assert.equal(r.run('liveConnection.automaticReport'),true);
 // A long report is not cut off 30 seconds after connecting.
 r.at(40000);await r.run('liveAutoDisconnect()');assert.equal(toggles,1);
 r.box.activeNotice=null;r.run('liveReplyActivity()');
 r.at(69999);await r.run('liveAutoDisconnect()');assert.equal(toggles,1);
 r.at(70001);r.box.busy=true;await r.run('liveAutoDisconnect()');assert.equal(toggles,1);
 r.box.busy=false;await r.run('liveAutoDisconnect()');assert.equal(toggles,2);
 r.run('liveConnection=null;livePausedContext=null');r.box.completionNotices.push({room_id:'room',job_id:'later'});
 await r.run('announceLiveCompletion()');assert.equal(toggles,2);
});

test('completed conversational question cancels only its own speculative reference announcement',()=>{
 const r=runtime();
 r.run('liveConnection.referenceReport={inputId:"earlier",facts:{id:"p"}}');
 r.run('cancelReferenceReportForInput(liveConnection,"current")');
 assert.equal(r.run('liveConnection.referenceReport.inputId'),'earlier');
 r.run('cancelReferenceReportForInput(liveConnection,"earlier")');
 assert.equal(r.run('liveConnection.referenceReport'),null);
 assert.ok(r.events.some(e=>e.type==='reference_report_superseded'));
});

test('delegating an already observed comparison acknowledges it without asking for duplicate narration',()=>{
 const r=runtime();
 r.run('liveConnection.rows.user={id:"u",text:"compare"};liveConnection.referenceObservedInput="u";queueReferenceReport({liveDelegation:"d"},{id:"p",items:[]},liveConnection)');
 assert.equal(r.sent.filter(e=>e.type==='session.commentary.append').length,0);
 assert.ok(r.sent.some(e=>e.type==='session.thinking.append'));
});

test('choosing a reference saves the original preference without starting an editing turn',async()=>{
 const r=runtime();let saved;
 r.box.presentationFeed=new Map();
 r.box.api=async(path,data)=>{
  if(path==='/visual-decision')return {handled:true,action:'select',item_id:'chosen'};
  assert.equal(path,'/choose');saved=data;return {ok:true};
 };
 await r.run('liveConnection.rows.user={id:"u",text:"I like that look"};conversationMemory.push({role:"user",text:"I like that look"});liveDelegate({delegation:{id:"selection"}},liveConnection);liveTaskQueue');
 assert.equal(r.calls.length,0);
 assert.equal(saved.item_id,'chosen');assert.equal(saved.feedback,'I like that look');
 assert.equal(saved.content_id,'A');
 assert.ok(r.events.some(e=>e.type==='reference_selected'&&e.saved));
});

test('multiple trailing corrections reclassify the latest reference request without starting Astra',async()=>{
 const r=runtime();r.box.presentationFeed=new Map();let lookups=0,rendered=0;
 r.box.renderReferences=()=>rendered++;
 r.box.presentationReady=async()=>({ok:true});
 r.box.setTimeout=()=>1;
 r.box.api=async path=>{
  if(path==='/visual-decision'){
   if(lookups++<2)r.run('liveConnection.rows.user.text+=" please";conversationMemory[0].text+=" please"');
   return {handled:true,action:'compare',selected_library_ids:['a']};
  }
  return {presentation:{id:'p',items:[{id:'i',title:'A',library_id:'a'}]}};
 };
 await r.run('liveConnection.rows.user={id:"u",text:"show references"};conversationMemory.push({role:"user",text:"show references"});liveDelegate({delegation:{id:"refresh"}},liveConnection);liveTaskQueue');
 assert.equal(lookups,3);assert.equal(rendered,1);assert.equal(r.calls.length,0);
 assert.ok(r.events.some(e=>e.type==='visual_decision_refreshed'));
});

test('edit completion reports current duration without treating old asset prose as a new change',()=>{
 const r=runtime();r.box.reasonRunning=true;
 r.run('turn={context,turn_id:"t",liveSession:liveConnection};livePresented(turn,{id:"p",revision:4,items:[{id:"i",title:"見本".repeat(200),kind:"scene",note:"OLD_EDIT",scene:{duration:6,description:"OLD_EDIT"}}]},{ok:true},{name:"revise_presentation"});liveBackendMessage(turn,{phase:"final_answer",text:"説明文だけ変更しました。"});');
 r.box.reasonRunning=false;r.run('flushPresentationReports()');
 const spoken=r.sent.filter(e=>e.type==='session.commentary.append');
 assert.equal(spoken.length,1);
 assert.equal(JSON.parse(spoken[0].content).revision,4);
 assert.ok(r.sent.some(e=>e.content.includes('"duration":6')));
 assert.ok(r.sent.some(e=>e.content.includes('説明文だけ変更しました')));
 assert.ok(!r.sent.some(e=>e.content.includes('OLD_EDIT')));
 for(const e of r.sent.filter(e=>e.content.startsWith('{')))assert.doesNotThrow(()=>JSON.parse(e.content));
});

test('muting input does not cut Dan speech; transport closes only after output settles',()=>{
 const r=runtime();let closed=0,paused=0;const track={enabled:true,stop:()=>{}};
 Object.assign(r.box,{micOn:false,mic:{getTracks:()=>[track]},audioPlaying:true,busy:false,reasonRunning:false,
  pc:{close:()=>closed++},audio:{pause:()=>paused++},clearInterval,completionNotices:[]});
 r.box.dc.send=()=>{};r.box.dc.close=()=>{};
 r.run('window.oldSession=liveConnection;muteLiveInput()');
 assert.equal(track.enabled,false);assert.equal(paused,0);assert.equal(closed,0);
 r.at(10000);r.run('finishMutedLive()');assert.equal(paused,0);
 r.box.audioPlaying=false;r.at(12999);r.run('finishMutedLive()');assert.equal(paused,0);
 r.at(13001);r.run('finishMutedLive();window.oldSession.finalize()');assert.equal(closed,1);
});

test('real recorded conversation updates memory without unsolicited Jev work',()=>{
 const r=runtime();let requests=0;
 r.box.api=async()=>{requests++;throw Error('transcript must not dispatch work');};
 const file='tests/fixtures/editor_live_consultation_transcript.json';
 const rows=JSON.parse(fs.readFileSync(file,'utf8'));
 assert.ok(rows.length>20);
 for(const [i,e] of rows.entries()){
   r.at(i*100);r.box.event={type:e.role==='user'?'session.input_transcript.delta':'session.output_transcript.delta',delta:e.delta,start_ms:e.start_ms,end_ms:e.end_ms};
   r.run('liveTranscript(event,liveConnection)');
 }
 assert.equal(requests,0);assert.equal(r.calls.length,0);
 assert.ok(r.box.conversationMemory.some(e=>e.role==='user'));
 assert.equal(r.events.filter(e=>e.type==='visual_decision_started').length,0);
});

test('consultation classification saves context without injecting competing instructions',async()=>{
 const r=runtime(),saved=new Map();
 r.box.localStorage={getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v)};
 r.box.api=async()=>({available:true,handled:true,action:'talk',consultation_memo:{version:2,facts:{brief:['film']},next:'conversation'}});
 r.run('liveConnection.rows.user={id:"u",text:"give me ideas"}');
 await r.run('visualDecision(liveConnection,[{role:"user",text:"give me ideas"}],[])');
 assert.equal(saved.size,1);assert.equal(r.sent.length,0);
});

test('superseded reference lookup does not start production or another unsolicited lookup',async()=>{
 const r=runtime();let requests=0;r.box.presentationFeed=new Map();
 r.run('liveConnection.rows.user={id:"before",text:"show references"}');
 r.box.api=async()=>{requests++;r.run('liveConnection.rows.user={id:"after",text:"answer in words first"}');return {handled:true,action:'talk'};};
 await r.run('liveDelegate({delegation:{id:"refine"}},liveConnection);liveTaskQueue');
 assert.equal(requests,1);assert.equal(r.calls.length,0);
 assert.equal(r.events.find(e=>e.type==='reference_selection_superseded').continued_to_backend,false);
});
