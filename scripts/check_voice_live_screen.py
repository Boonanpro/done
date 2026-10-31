"""Record actual browser tools -> private live screen -> production React UI.
No speech, phone call or external write is performed. The stage state is local.
"""
import asyncio,json,sys,time
from pathlib import Path
from datetime import timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
load_dotenv('/Users/mikihonda/done/.env')
from app.services.voice_tools import Host
from app.services.voice_external_screen import execute, scroll
from app.services import voice_stage as S
from app.services.voice_sideband import Dialogue
from app.services.owner import resolve_owner_user_id
from app.services.auth_service import create_access_token
from app.api.voicelog_routes import router
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
import uvicorn
from playwright.async_api import async_playwright
OUT=ROOT/'.data/voice-smooth';OUT.mkdir(parents=True,exist_ok=True)
async def main():
 phone='--phone' in sys.argv
 room='393bf4c2-0d5c-4157-89dc-9b89592517ba';S.ROOT=OUT/'state'
 stage=S.Stage(room,'stream-proof',Dialogue(),lambda *a,**kw:None)
 host=Host(resolve_owner_user_id(),room)
 app=FastAPI();app.include_router(router,prefix='/api/v1')
 app.add_middleware(CORSMiddleware,allow_origins=['http://127.0.0.1:3017'],allow_headers=['*'])
 server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8017,log_level='error'))
 running=asyncio.create_task(server.serve())
 while not server.started:await asyncio.sleep(.05)
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True)
  ctx=await browser.new_context(viewport={'width':1280,'height':900},record_video_dir=str(OUT/'recordings'),record_video_size={'width':1280,'height':900})
  token=create_access_token(resolve_owner_user_id(),'',timedelta(minutes=20))
  await ctx.add_cookies([{'name':'done_access_token','value':token,'domain':'127.0.0.1','path':'/'}])
  await ctx.add_init_script('localStorage.setItem("done-token",'+json.dumps(token)+')')
  page=await ctx.new_page()
  page.on("console",lambda m: print("console",m.type,m.text[:300],flush=True) if m.type=="error" else None)
  page.on("requestfailed",lambda r: print("failed",r.url.split("?")[0],r.failure,flush=True))
  async def serve(route):
   if '/image/' in route.request.url:
    from urllib.parse import urlsplit
    await route.continue_()
   else:
    await asyncio.sleep(.1);await route.fulfill(json=stage.state())
  await page.route('**/api/v1/voicelog/stage/**',serve)
  await page.goto('http://127.0.0.1:3017/voice-stage?room='+room,wait_until='domcontentloaded')
  report=[]
  try:
   if phone:
    await host.ask('call',name='phone',arguments={'action':'read','serial':'RFCXB0MSSTD'})
    await asyncio.sleep(3)
    r=await execute(host,stage,'phone',{'action':'screenshot','serial':'RFCXB0MSSTD'})
   else:
    r=await execute(host,stage,'browser',{'action':'open_target','url':'https://docs.python.org/ja/3/tutorial/','ready':{'selector':'h1'}})
   assert r['screen']['shown'];assert stage.image.endswith('.mjpeg'),stage.image
   print('stream selected',flush=True)
   await page.wait_for_function('()=>Array.from(document.images).some(i=>i.complete&&i.naturalWidth>0)',timeout=60000)
   await page.evaluate('''()=>{window.proofFrames=[];const image=document.querySelector('img');new MutationObserver(()=>window.proofFrames.push(performance.now())).observe(image,{attributes:true,attributeFilter:['src']})}''')
   await asyncio.sleep(1)
   # A real smooth scroll, executed through the same authenticated browser tool.
   start=time.monotonic()
   r=await scroll(host,stage,'down')
   await asyncio.sleep(2)
   count=await page.evaluate('window.proofFrames.length')
   assert count>=4,count
   await page.screenshot(path=str(OUT/('phone-ui-after.png' if phone else 'after.png')))
   report={'scope':('Android' if phone else 'browser')+' actual tool and actual screen UI; no speech recognition or call', 'frames_during_scroll':count,'operation_seconds':round(time.monotonic()-start-2,2),'screen':r['screen']}
   print(json.dumps(report),flush=True)
   await asyncio.sleep(2)
  finally:
   (OUT/('phone-result.json' if phone else 'result.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2))
   await ctx.close();await browser.close();host.close();stage.close()
   server.should_exit=True;await running
if __name__=='__main__':asyncio.run(main())
