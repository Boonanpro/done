"""Isolated built frontend + scene preview/export. Does not restart live services."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
from fastapi import FastAPI,Request
from fastapi.responses import Response
import httpx
app=FastAPI()
@app.get('/{path:path}')
async def proxy(path:str,request:Request):
    if path=='api/v1/editor-assistant/native-scene-script':
        return Response((ROOT/'app/static/editor-scene.js').read_text(encoding='utf-8'),media_type='application/javascript')
    port=8000 if path.startswith('api/') else 3002
    async with httpx.AsyncClient() as client:
        r=await client.get(f'http://127.0.0.1:{port}/{path}',params=request.query_params,timeout=30)
        return Response(r.content,status_code=r.status_code,headers={k:v for k,v in r.headers.items() if k.lower() not in ('content-length','content-encoding','transfer-encoding','connection')})

def wait(url):
    for _ in range(40):
        try:
            if urllib.request.urlopen(url,timeout=1).status==200:return
        except Exception:time.sleep(.25)
    raise RuntimeError('Staging server not ready')

def main():
    from playwright.sync_api import sync_playwright
    from app.services import timeline_draft as td,editor_film_plan as film,editor_presentation as presentation
    from app.services.editor_scene_export import materialize
    from app.api.production_asset_routes import _ffmpeg
    out=ROOT/'scratch/film-plan-dialogue';out.mkdir(exist_ok=True)
    dist=json.loads((ROOT/'.tmp/frontend_prod.json').read_text())['latest_build']
    env={**os.environ,'NEXT_DIST_DIR':dist,'NODE_ENV':'production'}
    children=[];handles=[]
    try:
        for name,cmd,cwd in [
            ('frontend',['C:/Program Files/nodejs/node.exe',str(ROOT/'frontend/node_modules/next/dist/bin/next'),'start','-p','3002','-H','127.0.0.1'],ROOT/'frontend'),
            ('proxy',[sys.executable,'-m','uvicorn','scripts.check_editable_scene_timeline:app','--host','127.0.0.1','--port','3003'],ROOT)]:
            log=(out/(name+'-staging.log')).open('w');handles.append(log)
            children.append(subprocess.Popen(cmd,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
        wait('http://127.0.0.1:3003/caption-frame')
        room='scene-timeline-check-'+str(time.time_ns());td._room_dir(room).mkdir(parents=True)
        td._write_contents_raw(room,[{'id':'film','timeline':{'format':'16:9','sequence':{'duration':0,'format':'16:9','tracks':[]}}}])
        film.update(room,'film',0,[{'op':'scene','id':'s','title':'歩く人物の配置','duration':2}],'検証')
        code="const dot=document.createElement('div');dot.style.cssText='position:absolute;width:80px;height:160px;background:#fff;top:90px';stage.append(dot);setFrame(t=>{dot.style.left=(params.x+t*70)+'px';});"
        item=presentation.present(room,'film',[{'kind':'scene','scene':{'code':code,'duration':2,'params':{'x':40}}}])['presentation']['items'][0]
        assert film.place_scene(room,'film','s',item['id'],0)['ok']
        sequence=td._read_contents_raw(room)[0]['timeline']['sequence']
        before=json.dumps(sequence,sort_keys=True)
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':640,'height':360})
            page.goto('http://127.0.0.1:3003/caption-frame')
            page.wait_for_function('()=>!!window.__setCaptionPayload')
            payload={'outW':640,'outH':360,'time':0,'captions':[{'id':'s','text':'','start':0,'end':2,'scene':item['scene']}]}
            page.evaluate('p=>window.__setCaptionPayload(p)',payload)
            page.wait_for_selector('[data-scene-ready="true"]',timeout=20000)
            page.screenshot(path=str(out/'timeline-scene-0.png'))
            page.evaluate('()=>window.__renderCaptionAt(1.5)')
            page.wait_for_function('()=>window.__nativeSceneTime===1.5')
            page.screenshot(path=str(out/'timeline-scene-1.png'))
            assert (out/'timeline-scene-0.png').read_bytes()!=(out/'timeline-scene-1.png').read_bytes()
            browser.close()
        exported=materialize(room,sequence,(640,360),12,_ffmpeg(),preview_origin='http://127.0.0.1:3003')
        assert 'asset_id' in exported['tracks'][0]['clips'][0]
        assert json.dumps(td._read_contents_raw(room)[0]['timeline']['sequence'],sort_keys=True)==before
        (out/'timeline-result.json').write_text(json.dumps({'room':room,'editable_sequence':sequence,'export_sequence':exported},ensure_ascii=False,indent=2),encoding='utf-8')
        print('PASS editable timeline, seek changes pixels, export materializes without changing source',flush=True)
    finally:
        for child in reversed(children):
            if child.poll() is None:child.terminate();child.wait(timeout=10)
        for handle in handles:handle.close()

if __name__=='__main__':main()
