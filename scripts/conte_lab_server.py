"""Loopback-only demo host; independent of Dan's active voice/server processes."""
import json, time
from pathlib import Path
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.services.conte_lab import TOOLS, INSTRUCTIONS, live_config
from app.services.editor_live import parse_session_response

ROOT=Path(__file__).resolve().parents[1]
app=FastAPI()
LOG=ROOT/'scratch/conte-lab/events.jsonl'
def log(data):
    LOG.parent.mkdir(parents=True,exist_ok=True)
    with LOG.open('a',encoding='utf-8') as f:f.write(json.dumps({'at':time.time(),**data},ensure_ascii=False)+'\n')

@app.middleware('http')
async def local_only(request,call_next):
    # Reject cross-origin requests before they can spend credits. No permissive CORS.
    if request.headers.get('host') not in ('127.0.0.1:3018','localhost:3018'):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':'Local demo only'},403)
    if request.method=='POST' and request.headers.get('origin') not in (None,'http://127.0.0.1:3018','http://localhost:3018'):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':'Origin rejected'},403)
    return await call_next(request)

async def provider(path,payload):
    if not settings.OPENAI_API_KEY:raise HTTPException(503,'API接続設定がありません')
    async with httpx.AsyncClient(timeout=60) as client:
        r=await client.post('https://api.openai.com/v1/'+path,headers={'Authorization':'Bearer '+settings.OPENAI_API_KEY},json=payload)
    if not r.is_success:raise HTTPException(502,f'モデル接続エラー ({r.status_code}): '+r.text[:350])
    return r

@app.post('/api/session')
async def session(request:Request):
    body=await request.json()
    r=await provider('live/sessions',{'session':live_config(body['state']),'transport':{'type':'webrtc','sdp':body['sdp']}})
    data=parse_session_response(r)
    log({'type':'session_created','id':data['session']['id']})
    return {'session':{'id':data['session']['id']},'transport':data['transport'],'backend_instructions':INSTRUCTIONS}

@app.post('/api/command')
async def command(request:Request):
    body=await request.json(); start=time.perf_counter()
    if len(json.dumps(body))>60000:raise HTTPException(413,'Scene too large')
    payload={'model':'gpt-6-astra','instructions':INSTRUCTIONS,'reasoning':{'effort':'low'},'tools':TOOLS,'parallel_tool_calls':False,
        'input':[{'role':'user','content':json.dumps({'scene':body['state'],'recent_dialogue':body.get('history',[])[-8:],'request':body['text']},ensure_ascii=False)}]}
    data=(await provider('responses',payload)).json()
    calls=[json.loads(i['arguments']) for i in data.get('output',[]) if i.get('type')=='function_call' and i.get('name')=='edit_scene']
    text=''.join(c.get('text','') for i in data.get('output',[]) for c in i.get('content',[]) if c.get('type')=='output_text')
    elapsed=round((time.perf_counter()-start)*1000)
    log({'type':'command','text':body['text'],'calls':calls,'elapsed_ms':elapsed,'usage':data.get('usage')})
    return {'calls':calls,'text':text,'elapsed_ms':elapsed}

@app.post('/api/log')
async def event(request:Request):
    data=await request.json()
    if len(json.dumps(data))<60000:log(data)
    return {'ok':True}

@app.get('/')
def home():return FileResponse(ROOT/'app/static/conte-lab/index.html',headers={'Cache-Control':'no-store'})
app.mount('/vendor',StaticFiles(directory=ROOT/'frontend/node_modules/three'),name='three')
app.mount('/lab',StaticFiles(directory=ROOT/'app/static/conte-lab'),name='lab')

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=3018)
