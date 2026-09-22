"""Actual API + sandboxed editor HTML preview, parameter edit and isolation."""
import asyncio,json,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'scratch/component-creative-cycle'

async def main():
 import httpx
 from playwright.async_api import async_playwright
 from app.services import timeline_draft as td
 room='component-creative-'+uuid.uuid4().hex[:8];cid='test';folder=td._room_dir(room);folder.mkdir(parents=True)
 sequence={'format':'16:9','duration':10,'tracks':[{'id':'v','type':'video','clips':[]}]}
 (folder/'contents.json').write_text(json.dumps([{'id':cid,'timeline':{'format':'16:9','sequence':sequence}}]),encoding='utf-8');(folder/'assets.json').write_text('[]')
 token=(Path.home()/'.done/native_token.txt').read_text().strip();port=8000 if '--production' in sys.argv else 8012
 base=f'http://127.0.0.1:{port}/api/v1/editor-assistant'
 plan=json.loads((OUT/'plan.json').read_text(encoding='utf-8'));results=[]
 async with httpx.AsyncClient(timeout=30,headers={'Authorization':'Bearer '+token}) as client,async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True);page=await browser.new_page(viewport={'width':1440,'height':900})
  await page.goto(base+'/page');await page.wait_for_function('typeof window.__updateEditorContext==="function"')
  await page.evaluate('({token,room,cid})=>{window.__editorBootstrap={token};window.__updateEditorContext({room_id:room,content_id:cid,playhead:0,selected:[]});}',{'token':token,'room':room,'cid':cid})
  r=await client.post(base+'/begin',json={'room_id':room,'content_id':cid});r.raise_for_status();turn=r.json()
  async def tool(name,args):
   r=await client.post(base+'/tool',json={'room_id':room,'turn_id':turn['turn_id'],'name':name,'args':args});r.raise_for_status();return r.json()
  for d in plan['directions']:
   source=(OUT/(d['id']+'.html')).read_text(encoding='utf-8')
   if d['id']=='c':source=source.replace('</body>','<script>if(window.danParams?.closing)document.getElementById("closing-copy").textContent=window.danParams.closing;</script></body>')
   started=time.perf_counter()
   shown=await tool('present_references',{'items':[{'kind':'scene','title':d['title'],'scene':{'html':source,'duration':10,'width':1920,'height':1080,'description':d['visual'],'params':{}}}]})
   ready=await page.evaluate('async p=>{renderReferences(p);return await presentationReady(p);}',shown['presentation'])
   elapsed=round((time.perf_counter()-started)*1000);assert ready['ok'],ready
   player=page.locator('.proposal-player').last;await player.evaluate("e=>e.control('pause')")
   seek=player.locator('input[type=range]');await seek.evaluate('(e)=>{e.value=6.8;e.dispatchEvent(new Event("input"));}')
   await page.wait_for_timeout(100)
   await player.locator('iframe').screenshot(path=str(OUT/(d['id']+'-editor.png')))
   result={'id':d['id'],'display_ms':elapsed,'ready':ready['ok'],'item_id':shown['presentation']['items'][0]['id']}
   if d['id']=='c':
    frame=await player.locator('iframe').element_handle();inner=await frame.content_frame()
    assert await inner.evaluate('(()=>{try{return parent.document.body?false:false}catch(e){return true}})()')
    snapshot='()=>[...document.querySelectorAll("#dan-html-stage *")].filter(e=>!e.closest("#closing-copy")).map(e=>{const s=getComputedStyle(e);return [e.tagName,e.id,s.transform,s.opacity,s.color,s.backgroundColor,s.fontSize]})'
    before_state=await inner.evaluate(snapshot)
    original=shown['presentation']['items'][0];started=time.perf_counter()
    changes=json.loads((OUT/'conversation.json').read_text(encoding='utf-8'))['revision']['changes']
    revision=await tool('revise_presentation',{'item_id':original['id'],'changes':changes})
    ready=await page.evaluate('async p=>{renderReferences(p);return await presentationReady(p);}',revision['presentation']);assert ready['ok'],ready
    result['revision_display_ms']=round((time.perf_counter()-started)*1000)
    revised=revision['presentation']['items'][0];assert revised['scene']['html']==source
    newer=page.locator('.proposal-player').last;await newer.evaluate("e=>e.control('pause')")
    await newer.locator('input[type=range]').evaluate('(e)=>{e.value=6.8;e.dispatchEvent(new Event("input"));}');await page.wait_for_timeout(100)
    newhandle=await newer.locator('iframe').element_handle();newinner=await newhandle.content_frame()
    assert before_state==await newinner.evaluate(snapshot),'An earlier scene changed'
    await newer.locator('input[type=range]').evaluate('(e)=>{e.value=9;e.dispatchEvent(new Event("input"));}');await page.wait_for_timeout(100)
    await newer.locator('iframe').screenshot(path=str(OUT/'revised-editor.png'))
    revised_html=source.replace('</body>','<script>document.getElementById("closing-copy").textContent="うまく言えなくても、大丈夫。";</script></body>')
    (OUT/'revised.html').write_text(revised_html,encoding='utf-8')
    # Compare intrinsic frames outside feed card positioning/subpixel rounding.
    probe=await browser.new_page(viewport={'width':1920,'height':1080},device_scale_factor=.5)
    frames=[]
    for name in ['c','revised']:
     await probe.goto((OUT/(name+'.html')).as_uri());await probe.evaluate('()=>{window.__timelines.sample.seek(6.8)}');frames.append(await probe.screenshot())
    await probe.close();assert frames[0]==frames[1]
    result.update(source_unchanged=True,earlier_frame_identical=True,parent_inaccessible=True)
   results.append(result);print(json.dumps(result),flush=True)
  # A forbidden remote script must not run or prevent a valid local timeline.
  html='<div data-composition-id="x">test</div><script src="https://example.com/untrusted.js"></script><script>document.fonts.ready.then(()=>{window.__timelines={x:gsap.timeline({paused:true}).to({}, {duration:2})};});</script>'
  requests=[];page.on('request',lambda r:requests.append(r.url))
  result=await tool('present_references',{'items':[{'kind':'scene','title':'Isolation test','scene':{'html':html,'duration':2}}]})
  ready=await page.evaluate('async p=>{renderReferences(p);return await presentationReady(p);}',result['presentation']);assert ready['ok']
  assert not any('example.com' in u for u in requests)
  await browser.close()
 assert td._find_content(td._read_contents_raw(room),cid)['timeline']['sequence']==sequence
 (OUT/('production-checks.json' if port==8000 else 'editor-checks.json')).write_text(json.dumps({'room':room,'port':port,'results':results,'remote_script_blocked':True,'timeline_unchanged':True},indent=2),encoding='utf-8')

if __name__=='__main__':asyncio.run(main())
