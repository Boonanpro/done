"""Exercise API tool dispatch and actual native preview; save silent recordings."""
import asyncio,json,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.test_direction_transfer import CASES,OUT

async def main():
 import httpx
 from playwright.async_api import async_playwright
 from app.services import timeline_draft as td
 room='direction-transfer-'+uuid.uuid4().hex[:8];cid='test';folder=td._room_dir(room);folder.mkdir(parents=True)
 sequence={'format':'16:9','duration':12,'tracks':[{'id':'v','type':'video','clips':[]}]}
 (folder/'contents.json').write_text(json.dumps([{'id':cid,'timeline':{'format':'16:9','sequence':sequence}}]),encoding='utf-8');(folder/'assets.json').write_text('[]')
 base='http://127.0.0.1:8012/api/v1/editor-assistant';token=(Path.home()/'.done/native_token.txt').read_text().strip()
 results=[]
 async with httpx.AsyncClient(timeout=30,headers={'Authorization':'Bearer '+token}) as client,async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True)
  for name,_,_ in CASES:
   data=json.loads((OUT/(name+'.json')).read_text(encoding='utf-8'))
   context=await browser.new_context(viewport={'width':1440,'height':900},record_video_dir=str(OUT/'recordings'),record_video_size={'width':1440,'height':900})
   page=await context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   await page.goto(base+'/page');await page.wait_for_function('typeof window.__updateEditorContext==="function"')
   await page.evaluate('({token,room,cid})=>{window.__editorBootstrap={token};window.__updateEditorContext({room_id:room,content_id:cid,playhead:0,selected:[]});}',{'token':token,'room':room,'cid':cid})
   response=await client.post(base+'/begin',json={'room_id':room,'content_id':cid});response.raise_for_status();turn=response.json()
   start=time.perf_counter();response=await client.post(base+'/tool',json={'room_id':room,'turn_id':turn['turn_id'],'name':'preview_direction_plan','args':{'plan':data['plan']}});response.raise_for_status();shown=response.json();assert shown.get('ok'),shown
   ready=await page.evaluate('async p=>{renderReferences(p);return await presentationReady(p);}',shown['presentation']);elapsed=round((time.perf_counter()-start)*1000);assert ready['ok'],ready
   item=shown['presentation']['items'][0];player=page.locator('.proposal-player').last
   await player.evaluate("e=>e.control('pause')")
   seek=player.locator('input[type=range]')
   for second in [0,1.5,3.9,4,5.5,7.9,8,9.5,11.9]:
    await seek.evaluate('(e,t)=>{e.value=t;e.dispatchEvent(new Event("input"));}',second);await page.wait_for_timeout(80)
    await player.locator('iframe').screenshot(path=str(OUT/f'{name}-{second}.png'))
   await seek.evaluate('(e)=>{e.value=0;e.dispatchEvent(new Event("input"));}')
   await player.evaluate("e=>e.control('play')");await page.wait_for_timeout(12100)
   assert not await player.evaluate('e=>e.dataset.failed'),await player.evaluate('e=>e.sceneError')
   # A single word change must preserve the other scenes and source program.
   original=item['scene']['params']['beats'];revision=await client.post(base+'/tool',json={'room_id':room,'turn_id':turn['turn_id'],'name':'revise_presentation','args':{'item_id':item['id'],'changes':[{'path':'/scene/params/beats/1/headline','value':'次の一歩へ'}]}});revision.raise_for_status();changed=revision.json();assert changed.get('ok'),changed
   revised=changed['presentation']['items'][0]
   assert revised['scene']['params']['beats'][0]==original[0] and revised['scene']['params']['beats'][2]==original[2]
   assert revised['scene']['code']==item['scene']['code']
   assert td._find_content(td._read_contents_raw(room),cid)['timeline']['sequence']==sequence
   video=page.video;await context.close();await video.save_as(str(OUT/(name+'.webm')))
   results.append({'case':name,'planning_ms':data['planning_ms'],'display_ms':elapsed,'ready':ready['ok'],'errors':errors,'partial_revision_preserved':True})
   print(json.dumps(results[-1]),flush=True)
  await browser.close()
 (OUT/'results.json').write_text(json.dumps({'room':room,'results':results},indent=2),encoding='utf-8')

if __name__=='__main__':asyncio.run(main())
