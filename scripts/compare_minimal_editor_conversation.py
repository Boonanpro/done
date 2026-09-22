"""Frozen 3-arm comparison. Real model APIs, simulated tools, no production changes."""
import asyncio, base64, copy, json, time, wave, argparse
from pathlib import Path
import websockets
from openai import AsyncOpenAI
from app.config import settings
from scripts.compare_editor_conversation_architectures import CASES, context, tool_result, message

OUT = Path('exports/minimal-conversation-comparison-20260910')
OLD = json.loads(Path('exports/conversation-architecture-comparison-20260909-v2/memory-current-0.json').read_text(encoding='utf-8'))['configuration']
LEAN = '''あなたは動画制作エディターのダンです。ユーザーと日本語で会話し、意図を理解して制作・編集を進めます。会話原文と作品情報を参照でき、必要な調査・操作には道具を使えます。今回の予算・許可・変更対象はユーザーの発言に従います。'''
TOOLS = [copy.deepcopy(t) for t in OLD[1] if t['name'] not in {'save_brief', 'delegate_edit', 'update_work', 'set_project_scope'}]
TOOLS.append({'type':'function','name':'request_production','description':'制作担当へ作業を依頼する。アプリが話者付き会話原文・参考・作品状態をそのまま渡し、担当が必要な調査と制作を行う。依頼文や作業分類の入力は不要。', 'parameters':{'type':'object','properties':{},'required':[]}})
ARMS = ['rt_old','rt_lean','gpt_lean']

def config(arm): return OLD if arm == 'rt_old' else (LEAN, TOOLS)

def result(name, args, case):
    if name == 'request_production':
        return {'ok':True,'job_id':'fixture-new','status':'queued','raw_messages':case['messages'], 'message':'依頼を受け付けました。成果物はまだありません。'}
    return tool_result(name, args, case)

def record_call(r, o, case):
    name=o['name'];args=json.loads(o['arguments']);value=result(name,args,case)
    r['calls'].append({'name':name,'args':args,'at_seconds':time.monotonic()-r['t0'],'result':value})
    return value

async def rt(case,r,audio_path=None, relay=None):
    prompt,ts=config(r['arm'])
    if relay is not None: prompt='入力された文章だけを、そのまま日本語で読み上げてください。';ts=[]
    voice = r['phase']=='audio' or relay is not None
    modality='audio' if voice else 'text'
    async with websockets.connect('wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1',additional_headers={'Authorization':'Bearer '+settings.OPENAI_API_KEY},max_size=16*1024*1024) as ws:
        async def send(o): await ws.send(json.dumps(o,ensure_ascii=False))
        session={'type':'realtime','model':'gpt-realtime-2.1','instructions':prompt,'tools':ts,'reasoning':{'effort':'high'},'max_output_tokens':4096,'output_modalities':[modality]}
        session['audio']={'input':{'format':{'type':'audio/pcm','rate':24000},'turn_detection':None,'transcription':{'model':'gpt-4o-transcribe'}},'output':{'voice':'marin','format':{'type':'audio/pcm','rate':24000}}}
        await send({'type':'session.update','session':session})
        while True:
            e=json.loads(await asyncio.wait_for(ws.recv(),45))
            if e['type']=='error':raise RuntimeError(str(e['error']))
            if e['type']=='session.updated':break
        if relay is not None:
            await send({'type':'conversation.item.create','item':message('user',relay)})
        else:
            await send({'type':'conversation.item.create','item':message('system',json.dumps(context(case),ensure_ascii=False))})
            for role,txt in (case['messages'][:-1] if audio_path else case['messages']):
                await send({'type':'conversation.item.create','item':message(role,txt)})
        r.setdefault('t0',time.monotonic())
        if audio_path:
            with wave.open(str(audio_path)) as f: pcm=f.readframes(f.getnframes())
            await send({'type':'input_audio_buffer.append','audio':base64.b64encode(pcm).decode()})
            await send({'type':'input_audio_buffer.commit'})
        pcm_out=bytearray()
        for _ in range(8):
            await send({'type':'response.create','response':{'output_modalities':[modality]}})
            while True:
                e=json.loads(await asyncio.wait_for(ws.recv(),120))
                if e['type']=='error':raise RuntimeError(str(e['error']))
                if e['type']=='conversation.item.input_audio_transcription.completed':r['asr']=e.get('transcript')
                if e['type'] in {'response.output_text.delta','response.text.delta'}:r.setdefault('first_text_seconds',time.monotonic()-r['t0'])
                if e['type'] in {'response.output_audio.delta','response.audio.delta'}:
                    r.setdefault('first_audio_seconds',time.monotonic()-r['t0']);pcm_out.extend(base64.b64decode(e['delta']))
                if e['type']=='response.done':break
            response=e['response'];r.setdefault('responses',[]).append(response)
            if response['status']!='completed':raise RuntimeError(str(response.get('status_details')))
            calls=[o for o in response.get('output',[]) if o['type']=='function_call']
            for o in response.get('output',[]):
                if o['type']=='message':r.setdefault('answers',[]).append(''.join(c.get('transcript',c.get('text','')) for c in o.get('content',[])))
            for call in calls:
                value=record_call(r,call,case)
                await send({'type':'conversation.item.create','item':{'type':'function_call_output','call_id':call['call_id'],'output':json.dumps(value,ensure_ascii=False)}})
            if not calls:break
        else:raise RuntimeError('tool round ceiling; unfinished')
        if pcm_out:
            with wave.open(str(OUT/(r['id']+'.wav')),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(pcm_out)

async def gpt(case,r,audio_path=None):
    prompt,ts=config(r['arm']);case=copy.deepcopy(case)
    async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY,timeout=120,max_retries=0) as client:
        r['t0']=time.monotonic()
        if audio_path:
            with open(audio_path,'rb') as f:asr=await client.audio.transcriptions.create(model='gpt-4o-transcribe',file=f,language='ja')
            r['asr']=asr.text;r['asr_seconds']=time.monotonic()-r['t0'];case['messages'][-1]=('user',asr.text)
        inputs=[message('system',json.dumps(context(case),ensure_ascii=False))]+[message(*m) for m in case['messages']]
        api_tools=[{'type':'function','name':t['name'],'description':t['description'],'parameters':t['parameters'],'strict':False} for t in ts]
        for _ in range(8):
            stream=await client.responses.create(model='gpt-6-astra',instructions=prompt,input=inputs,tools=api_tools,reasoning={'effort':'high'},max_output_tokens=4096,stream=True,store=False)
            response=None
            async for e in stream:
                if e.type=='response.output_text.delta':r.setdefault('first_text_seconds',time.monotonic()-r['t0'])
                if e.type=='response.completed':response=e.response.model_dump()
                if e.type in {'error','response.failed','response.incomplete'}:raise RuntimeError(str(e)[:900])
            if response is None:raise RuntimeError('no completed response')
            r.setdefault('responses',[]).append(response)
            inputs.extend({k:v for k,v in o.items() if k!='status'} for o in response['output'])
            calls=[o for o in response['output'] if o['type']=='function_call']
            for o in response['output']:
                if o['type']=='message':r.setdefault('answers',[]).extend(c['text'] for c in o['content'] if c['type']=='output_text')
            for call in calls:
                value=record_call(r,call,case)
                inputs.append({'type':'function_call_output','call_id':call['call_id'],'output':json.dumps(value,ensure_ascii=False)})
            if not calls:break
        else:raise RuntimeError('tool round ceiling; unfinished')
        r['decision_seconds']=time.monotonic()-r['t0']
        if audio_path:
            answer='\n'.join(r.get('answers',[]));r['text_answer']=answer
            await rt(case,r,relay=answer)

async def one(case,arm,rep,phase):
    rid=f'{phase}-{case["id"]}-{arm}-{rep}';path=OUT/(rid+'.json')
    if path.exists():return
    r={'id':rid,'arm':arm,'phase':phase,'case':case,'repeat':rep,'calls':[],'configuration':config(arm)}
    try:
        audio=OUT/(case['id']+'-input.wav') if phase=='audio' else None
        await (gpt(case,r,audio) if arm=='gpt_lean' else rt(case,r,audio))
        r['elapsed_seconds']=time.monotonic()-r['t0'];r['ok']=True
    except Exception as e:r['ok']=False;r['error']=str(e)[:1800]
    r.pop('t0',None);path.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(rid,r['ok'],round(r.get('elapsed_seconds',0),2),[c['name'] for c in r['calls']],r.get('error',''),flush=True)

async def main(phase):
    OUT.mkdir(parents=True,exist_ok=True)
    cases=CASES if phase=='text' else [c for c in CASES if c['id'] in {'memory','budget_change'}]
    if phase=='audio':
        for c in cases:
            target=OUT/(c['id']+'-input.wav')
            if not target.exists():
                r={'id':c['id']+'-input','phase':'audio','arm':'rt_lean','calls':[]}
                await rt(c,r,relay=c['messages'][-1][1])
    protocol={'phase':phase,'cases':cases,'repeats':2,'arms':ARMS,'configs':{a:config(a) for a in ARMS},'reasoning':'high for both models','tools':'fixed simulated results; no editor/search/production side effects','limits':'two repeats, bundled harness intervention; audio uses synthetic final utterance/manual end-of-turn, GPT uses ASR then full answer then relay, not streaming speech or live interruption; text timing excludes connection setup'}
    (OUT/(phase+'-protocol.json')).write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    sem=asyncio.Semaphore(2)
    async def limited(*args):
        async with sem:await one(*args)
    work=[]
    for rep in range(2):
        for i,c in enumerate(cases):
            order=ARMS[(i+rep)%3:]+ARMS[:(i+rep)%3]
            work.extend(limited(c,a,rep,phase) for a in order)
    await asyncio.gather(*work)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=['text','audio'],default='text');args=ap.parse_args();asyncio.run(main(args.phase))
