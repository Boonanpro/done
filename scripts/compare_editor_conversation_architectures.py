"""Real API conversation comparison; all editor/search/production tools are fixtures.

No live editor, external search, video generation or job is mutated. Text input
isolates reasoning from ASR/VAD. Audio output is generated and saved, not played.
"""
import asyncio, base64, copy, json, time, wave
from pathlib import Path
import websockets
from openai import AsyncOpenAI
from app.config import settings
from app.api.editor_assistant_routes import EDITOR_INSTRUCTIONS, EDITOR_TOOLS, REALTIME_MODEL
from app.services.editor_production_contract import CONVERSATION_AUTHORITY, PRODUCTION_AUTHORITY
from scripts.compare_realtime_handoff_formats import CASES as ORIGINAL_CASES

OUT=Path('exports/conversation-architecture-comparison-20260909-v2')
OUT.mkdir(parents=True,exist_ok=True)
CASES=copy.deepcopy(ORIGINAL_CASES)+[
 {'id':'memory','messages':[
  ('user','仕事帰りの人が、一人でも気兼ねなく寄れる焼き鳥屋の動画にしたい。'),
  ('assistant','落ち着いて一息つけるお店として伝える方向ですね。'),
  ('user','ところで、今どんな人向けに作ってるんだっけ？')], 'brief':{},'reference':''},
 {'id':'search','messages':[
  ('user','一人客が仕事帰りに寄りやすい焼き鳥屋の紹介動画を作りたい。'),
  ('assistant','入りやすさが伝わる参考を探せます。'),
  ('user','じゃあそういう雰囲気の参考動画を探して、実物を二つ見せて。まだ制作はしないで。')], 'brief':{},'reference':''},
 {'id':'stop','messages':[
  ('user','日本対ブラジルの見本を作って。'),('assistant','制作を始めました。'),
  ('user','あ、今の制作は止めて。会話はこのまま続けたい。')], 'brief':{},'reference':''},
]

def configuration(arm):
    prompt=EDITOR_INSTRUCTIONS; ts=copy.deepcopy(EDITOR_TOOLS)
    if arm=='astra_raw':
        prompt='\n'.join(l for l in prompt.splitlines() if 'save_brief' not in l)
        prompt=prompt.replace(CONVERSATION_AUTHORITY,PRODUCTION_AUTHORITY)
        prompt+='\nあなたはユーザーと話すGPT6です。アプリから渡された話者付きの会話原文を直接読んで、回答・調査・制作判断を行います。返答の文章は音声側がそのまま読み上げます。会話と実行はアプリが記録します。delegate_editは判断済みの仕事を実行する作業系への接続です。'
        ts=[t for t in ts if t['name']!='save_brief']
    return prompt,ts

def context(case):
    return {'content_id':'isolated-comparison','duration':0,'clips':[],
            'creative_brief':case['brief'],'reference_ids':['ref1'] if case['reference'] else [],
            'reference_description':case['reference'],
            'active_jobs':[{'id':'fixture-active','status':'running'}] if case['id']=='stop' else []}

def tool_result(name,args,case):
    # Fixed fixtures, never invoke production modules. URLs are deliberately fictional.
    if name in {'read_editor_context','timeline_state'}:return {'ok':True,**context(case)}
    if name=='read_references':return {'ok':True,'references':[{'id':'ref1','analysis':case['reference']}]}
    if name in {'search_references','search_web_references'}:
        return {'ok':True,'results':[{'id':f'search{i}','title':title,'url':f'https://example.invalid/reference-{i}',
            'description':desc} for i,title,desc in [(1,'仕事帰りのカウンター','一人客が暖簾をくぐり、カウンターで焼き鳥を楽しむ短い店紹介。'),(2,'ひと息つける店','落ち着いた店内、料理と一人客の表情を組み合わせた短い映像。')]]}
    if name=='resolve_reference':return {'ok':True,'item':{'kind':'video','url':args.get('source',args.get('url','https://example.invalid/reference-1')),'title':'確認用の参考映像'},'reference_id':'fixture-resolved'}
    if name=='project_status':return {'ok':True,'active_jobs':context(case)['active_jobs'],'active_count':len(context(case)['active_jobs'])}
    if name=='delegate_edit':return {'ok':True,'job_id':'fixture-new','status':'queued','message':'作業を受け付けました。成果物はまだありません。'}
    if name=='stop_production':return {'ok':True,'stopped':['fixture-active']}
    if name=='list_assets':return {'ok':True,'assets':[]}
    if name=='save_brief':return {'ok':True,'saved':args}
    return {'ok':True}

def message(role,txt,realtime=False):
    return {'type':'message','role':role,'content':[{'type':'output_text' if role=='assistant' else 'input_text','text':txt}]}

async def realtime(case,record,relay=None):
    prompt,ts=configuration('current')
    if relay is not None:
        prompt='あなたは音声出力を担当します。入力の文章をそのまま日本語で読み上げてください。内容の追加、要約、挨拶、判断、ツール操作は不要です。';ts=[]
    async with websockets.connect('wss://api.openai.com/v1/realtime?model='+REALTIME_MODEL,
          additional_headers={'Authorization':'Bearer '+settings.OPENAI_API_KEY},max_size=16*1024*1024,open_timeout=30) as ws:
        async def send(x):await ws.send(json.dumps(x,ensure_ascii=False))
        await send({'type':'session.update','session':{'type':'realtime','model':REALTIME_MODEL,'instructions':prompt,'tools':ts,
          'reasoning':{'effort':'high'},'max_output_tokens':4096,'output_modalities':['audio'],
          'audio':{'output':{'voice':'marin','format':{'type':'audio/pcm','rate':24000}}}}})
        while True:
            e=json.loads(await asyncio.wait_for(ws.recv(),45))
            if e['type']=='error':raise RuntimeError(str(e['error']))
            if e['type']=='session.updated':break
        if relay is None:
            await send({'type':'conversation.item.create','item':message('system',json.dumps(context(case),ensure_ascii=False))})
            for role,txt in case['messages']:await send({'type':'conversation.item.create','item':message(role,txt)})
        else:await send({'type':'conversation.item.create','item':message('user',relay)})
        if 't0' not in record:record['t0']=time.monotonic()
        pcm=bytearray()
        for _ in range(6):
            await send({'type':'response.create','response':{'output_modalities':['audio']}})
            while True:
                e=json.loads(await asyncio.wait_for(ws.recv(),100))
                if e['type']=='error':raise RuntimeError(str(e['error']))
                if e['type'] in {'response.output_audio.delta','response.audio.delta'}:
                    record.setdefault('first_audio_seconds',time.monotonic()-record['t0'])
                    pcm.extend(base64.b64decode(e['delta']))
                if e['type']=='response.done':break
            r=e['response'];record.setdefault('audio_responses',[]).append(r)
            if r['status']!='completed':raise RuntimeError(str(r.get('status_details')))
            calls=[o for o in r.get('output',[]) if o['type']=='function_call']
            for o in r.get('output',[]):
                if o['type']=='message':
                    txt=''.join(c.get('transcript',c.get('text','')) for c in o.get('content',[]))
                    record.setdefault('spoken',[]).append(txt)
            for call in calls:
                args=json.loads(call['arguments']);name=call['name'];result=tool_result(name,args,case)
                record['calls'].append({'name':name,'args':args,'at_seconds':time.monotonic()-record['t0'],'result':result})
                await send({'type':'conversation.item.create','item':{'type':'function_call_output','call_id':call['call_id'],'output':json.dumps(result,ensure_ascii=False)}})
            if not calls:break
        if pcm:
            with wave.open(str(OUT/(record['id']+'.wav')),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(pcm)
        record['audio_complete_seconds']=time.monotonic()-record['t0']

async def astra(case,record):
    prompt,ts=configuration('astra_raw')
    api_tools=[{'type':'function','name':t['name'],'description':t['description'],'parameters':t['parameters'],'strict':False} for t in ts]
    inputs=[message('system',json.dumps(context(case),ensure_ascii=False))]+[message(*m) for m in case['messages']]
    client=AsyncOpenAI(api_key=settings.OPENAI_API_KEY,timeout=120,max_retries=0)
    record['t0']=time.monotonic();texts=[]
    try:
        for _ in range(6):
            stream=await client.responses.create(model='gpt-6-astra',instructions=prompt,input=inputs,tools=api_tools,
                reasoning={'effort':'high'},max_output_tokens=4096,stream=True,store=False)
            response=None
            async for e in stream:
                if e.type=='response.output_text.delta':record.setdefault('first_text_seconds',time.monotonic()-record['t0'])
                if e.type=='response.completed':response=e.response
                if e.type in {'response.failed','response.incomplete','error'}:raise RuntimeError(str(e)[:900])
            if response is None:raise RuntimeError('Missing response.completed')
            r=response.model_dump();record.setdefault('astra_responses',[]).append(r)
            calls=[o for o in r['output'] if o['type']=='function_call']
            inputs.extend({k:v for k,v in o.items() if k!='status'} for o in r['output'])
            for o in r['output']:
                if o['type']=='message':texts.extend(c['text'] for c in o.get('content',[]) if c['type']=='output_text')
            for call in calls:
                name=call['name'];args=json.loads(call['arguments']);result=tool_result(name,args,case)
                record['calls'].append({'name':name,'args':args,'at_seconds':time.monotonic()-record['t0'],'result':result})
                inputs.append({'type':'function_call_output','call_id':call['call_id'],'output':json.dumps(result,ensure_ascii=False)})
            if not calls:break
        record['answer']='\n'.join(texts);record['decision_complete_seconds']=time.monotonic()-record['t0']
        if record['answer']:await realtime(case,record,relay=record['answer'])
    finally:await client.close()

async def run(arm,case,repeat):
    rid=f"{case['id']}-{arm}-{repeat}";path=OUT/(rid+'.json')
    if path.exists():return
    record={'id':rid,'arm':arm,'case':case,'repeat':repeat,'calls':[],'configuration':configuration(arm)}
    try:
        if arm=='current':await realtime(case,record)
        else:await astra(case,record)
        record['ok']=True
    except Exception as e:record['error']=str(e)[:1500];record['ok']=False
    record.pop('t0',None)
    path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(rid,record['ok'],'audio',round(record.get('first_audio_seconds',0),2),'calls',[c['name'] for c in record['calls']],record.get('error',''),flush=True)

async def main():
    protocol={'cases':[c['id'] for c in CASES],'repeats':2,'arms':['current','astra_raw'],
       'concurrency':2,'input':'text transcripts','output':'real PCM audio, not played',
       'tools':'fixed mock results; zero real editor/search/production actions',
       'timing':'after initial input preparation; proposed includes full text completion then relay connection/audio; baseline connection excluded',
       'limitations':'not ASR/VAD, live interruptions, actual search/render latency, or simultaneous conversation; no streamed text-to-audio overlap yet'}
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    sem=asyncio.Semaphore(2)
    async def one(*args):
        async with sem:await run(*args)
    tasks=[]
    for repeat in range(2):
        for case in CASES:
            for arm in (['current','astra_raw'] if repeat==0 else ['astra_raw','current']):tasks.append(one(arm,case,repeat))
    await asyncio.gather(*tasks)

if __name__=='__main__':asyncio.run(main())
