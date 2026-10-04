"""Local conversation demo; does not restart or modify the live editor."""
import asyncio,json,time,uuid,os
from pathlib import Path
import httpx
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.services import film_studio as studio
from app.services.editor_live import parse_session_response

ROOT=Path(__file__).resolve().parents[1]
app=FastAPI();jobs={};lock=asyncio.Lock();calls={};displayed={}
PORT=int(os.environ.get('DAN_FILM_STUDIO_PORT','3020'))
LOG=ROOT/'scratch/film-studio'/studio.ROOM/'events.jsonl'
def log(kind,**data):
    LOG.parent.mkdir(parents=True,exist_ok=True)
    with LOG.open('a',encoding='utf-8') as f:f.write(json.dumps({'at':time.time(),'type':kind,**data},ensure_ascii=False)+'\n')

@app.middleware('http')
async def local(request,call_next):
    hosts=(f'127.0.0.1:{PORT}',f'localhost:{PORT}')
    if request.headers.get('host') not in hosts:return JSONResponse({'detail':'Local only'},403)
    if request.method=='POST' and request.headers.get('origin') not in (None,*['http://'+h for h in hosts]):return JSONResponse({'detail':'Origin rejected'},403)
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    if request.url.path.startswith('/api/v1/editor-assistant/scene-vendor/'):
        response.headers['Access-Control-Allow-Origin']='*'
    return response

async def provider(path,payload):
    if not settings.OPENAI_API_KEY:raise ValueError('OpenAI API未設定')
    async with httpx.AsyncClient(timeout=180) as client:
        r=await client.post('https://api.openai.com/v1/'+path,headers={'Authorization':'Bearer '+settings.OPENAI_API_KEY},json=payload)
    if not r.is_success:raise ValueError('モデル接続エラー '+str(r.status_code))
    return r

def snapshot():
    return {**studio.state(),'jobs':list(jobs.values())[-15:],'displayed':displayed}

@app.get('/')
def home():return FileResponse(ROOT/'app/static/film-studio/index.html')

@app.get('/api/state')
def state():return snapshot()

@app.get('/api/package')
def package():
    s=studio.state()
    return JSONResponse(s,headers={'Content-Disposition':'attachment; filename="film-preparation.json"'})

async def call_tool(name,args):
    start=time.perf_counter()
    try:result=await studio.execute(name,args)
    except Exception as e:
        log('tool_failed',name=name,error=str(e));return {'ok':False,'error':str(e)}
    log('tool_completed',name=name,arguments=args,elapsed_ms=round((time.perf_counter()-start)*1000),routing=result.get('routing'))
    if name=='get_state':result['displayed']=displayed
    return result

async def run_text(ident,text,focus):
    job=jobs[ident]
    async with lock:
        job.update(status='running',label='話の内容から提案を考えています')
        try:
            prior=studio.context();studio.dialogue('user',text)
            inputs=[{'role':'user','content':json.dumps({'project':prior,'selected_scene':focus,'request':text},ensure_ascii=False)}]
            for _ in range(10):
                response=(await provider('responses',{'model':'gpt-6-astra','instructions':studio.INSTRUCTIONS,
                    'tools':studio.tools(),'parallel_tool_calls':False,'reasoning':{'effort':'medium'},'input':inputs,'store':False})).json()
                log('model_response',job_id=ident,usage=response.get('usage'))
                inputs.extend(response.get('output',[]));todo=[i for i in response.get('output',[]) if i.get('type')=='function_call']
                if not todo:
                    answer=''.join(c.get('text','') for i in response.get('output',[]) for c in i.get('content',[]) if c.get('type')=='output_text')
                    studio.dialogue('assistant',answer);job.update(status='completed',label='',reply=answer);return
                for item in todo:
                    job['label']=studio.LABELS.get(item['name'],'提案を更新しています')
                    result=await call_tool(item['name'],json.loads(item['arguments']))
                    inputs.append({'type':'function_call_output','call_id':item['call_id'],'output':json.dumps(result,ensure_ascii=False)})
            raise ValueError('一度の処理が長くなったため区切りました。保存済みの内容から続けられます')
        except Exception as e:job.update(status='failed',label=str(e));log('job_failed',error=str(e))
        finally:job['ended_at']=time.time()

@app.post('/api/message')
async def message(request:Request):
    body=await request.json();text=str(body.get('text','')).strip()
    if not text or len(text)>12000:raise HTTPException(422,'指示は1〜12000文字です')
    if any(j['status'] in ('running','queued') for j in jobs.values()):raise HTTPException(409,'直前の処理が完了してから送信してください')
    ident=uuid.uuid4().hex;jobs[ident]={'id':ident,'status':'queued','label':'会話を受け取りました','started_at':time.time()}
    asyncio.create_task(run_text(ident,text,body.get('focus')))
    return {'id':ident}

@app.post('/api/session')
async def session(request:Request):
    body=await request.json()
    config={'model':'gpt-live-1','audio':{'output':{'voice':'meridian'}},
        'instructions':'あなたはダン。日本語で自然に短く会話します。ユーザーは監督として映画を詰めています。作品の相談・提案・変更は文脈と原文を保ってバックエンドへ委譲します。単なる相槌には不要です。接続しただけで話し出さず発言を待ってください。結果が来たら会話として伝え、処理分類や内部状態を読み上げません。',
        'delegation':{'type':'responses','responses':{'model':'gpt-6-astra','instructions':studio.INSTRUCTIONS+'\nCurrent project: '+json.dumps(studio.context(),ensure_ascii=False),
            'tools':studio.tools(),'parallel_tool_calls':False,'reasoning':{'effort':'medium'}}}}
    data=parse_session_response(await provider('live/sessions',{'session':config,'transport':{'type':'webrtc','sdp':body['sdp']}}))
    log('voice_session_created',session_id=data['session']['id'])
    return {'session':{'id':data['session']['id']},'transport':data['transport'],'instructions':studio.INSTRUCTIONS}

@app.post('/api/tool')
async def tool(request:Request):
    body=await request.json();ident=body['call_id']
    if ident not in calls:
        async def run():
            async with lock:
                jobs[ident]={'id':ident,'status':'running','label':studio.LABELS.get(body['name'],'相談を進めています'),'started_at':time.time()}
                try:return await call_tool(body['name'],body['arguments'])
                finally:jobs[ident].update(status='completed',label='',ended_at=time.time())
        calls[ident]=asyncio.create_task(run())
    return await asyncio.shield(calls[ident])

@app.post('/api/event')
async def event(request:Request):
    body=await request.json()
    if len(json.dumps(body))>20000:raise HTTPException(413,'Event too large')
    log('browser',event=body)
    if body.get('type')=='transcript' and body.get('role') in ('user','assistant'):
        studio.dialogue(body['role'],str(body.get('text','')))
    if body.get('type')=='transcript_update' and body.get('role') in ('user','assistant'):
        def update(c):
            row=next((r for r in c['studio_dialogue'] if r.get('id')==body.get('id')),None)
            if row:
                if len(str(body.get('text','')))>=len(row['text']):row['text']=str(body.get('text',''))
            else:c['studio_dialogue'].append({'id':body['id'],'role':body['role'],'text':str(body.get('text','')),'at':time.time()})
        studio.mutate(update)
    if body.get('type')=='display':displayed[body['id']]={'ok':body.get('ok'),'at':time.time()}
    return {'ok':True}

@app.get('/api/v1/production-assets/media')
def media(room_id:str,asset_id:str,variant:str='original'):
    if room_id!=studio.ROOM:raise HTTPException(404)
    p=studio.td._room_dir(room_id)/'assets.json'
    rows=json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
    row=next((r for r in rows if r['id']==asset_id),None)
    if not row:raise HTTPException(404)
    return FileResponse(row['local_path'])

@app.get('/api/v1/editor-assistant/scene-vendor/{name}')
def vendor(name:str):
    files={'three.module.min.js':ROOT/'frontend/node_modules/three/build/three.module.min.js',
           'three.core.min.js':ROOT/'frontend/node_modules/three/build/three.core.min.js',
           'gsap.min.js':ROOT/'frontend/node_modules/gsap/dist/gsap.min.js'}
    if name not in files:raise HTTPException(404)
    return FileResponse(files[name],media_type='application/javascript')

@app.get('/shared/{name}')
def shared(name:str):
    if name not in ('editor-scene.js','editor-proposals.js'):raise HTTPException(404)
    return FileResponse(ROOT/'app/static'/name,media_type='application/javascript')

app.mount('/studio',StaticFiles(directory=ROOT/'app/static/film-studio'),name='studio')
if __name__=='__main__':
    import uvicorn
    studio.initialize();uvicorn.run(app,host='127.0.0.1',port=PORT)
