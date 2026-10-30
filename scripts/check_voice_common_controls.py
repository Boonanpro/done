"""Real artifact screens driven through StageFrame and the common control protocol.
No calls are placed; these timings begin at command dispatch, NOT at speech end.
All artifact writes are refused. The call-state HTTP edges use an isolated in-process
Stage; the iframe, DOM discovery, React handlers and receipt round-trip are real.
"""
import asyncio,json,os,sys,time,tempfile,uuid
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));load_dotenv('/Users/mikihonda/done/.env')
from app.services.auth_service import create_access_token
from app.services.owner import resolve_owner_user_id
from app.services import voice_stage as S,voice_screen as C
from app.services.voice_sideband import Dialogue
from playwright.async_api import async_playwright

async def main():
 base=os.environ.get('VOICE_TEST_BASE','http://127.0.0.1:3014')
 proof=ROOT/'.data/voice-proof';proof.mkdir(parents=True,exist_ok=True)
 tmp=tempfile.TemporaryDirectory();S.ROOT=C.ROOT=Path(tmp.name)
 report={'scope':'actual site DOM and frame transport; no speech model, microphone, or phone call','operations':[],'blocked_writes':[]}
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True)
  token=create_access_token(resolve_owner_user_id(),'',timedelta(minutes=30))
  context=await browser.new_context(viewport={'width':1280,'height':800},record_video_dir=str(proof/'operations'),record_video_size={'width':1280,'height':800})
  await context.add_cookies([{'name':'done_access_token','value':token,'domain':'127.0.0.1','path':'/'}])
  await context.add_init_script('localStorage.setItem("done-token",'+json.dumps(token)+')')
  async def protect(route):
   if route.request.method not in ['GET','HEAD','OPTIONS']:
    report['blocked_writes'].append(route.request.url.split('/api/',1)[-1])
    await route.fulfill(status=403,json={'detail':'Test is read only'});return
   await route.continue_()
  await context.route('**/api/**',protect)
  try:
   for slug in ['dev-lead','fukurou-inbox','x-operation']:
    stage=S.Stage(str(uuid.uuid4()),'isolated-'+slug,Dialogue(),lambda *a,**kw:None)
    stage._apply(slug,frame='/preview/'+slug)
    page=await context.new_page()
    async def serve(route):
     if route.request.method=='POST':
      body=route.request.post_data_json
      await route.fulfill(json={'accepted':C.accept(stage.room_id,stage.state(),body)})
     else:
      await asyncio.sleep(.08)
      await route.fulfill(json=stage.state())
    await page.route('**/api/v1/voicelog/stage/**',serve)
    await page.goto(base+'/voice-stage?room='+stage.room_id,wait_until='domcontentloaded')
    for _ in range(120):
     screen=C.current(stage)
     if screen and len(screen.get('controls',[]))>5: break
     await asyncio.sleep(.25)
    await asyncio.sleep(2)
    screen=C.current(stage)
    if not screen: raise AssertionError(slug+': no screen snapshot')
    (proof/(slug+'-controls.json')).write_text(json.dumps(screen,ensure_ascii=False,indent=2))
    print(slug,[(c['name'],c['role'],c['risk']) for c in screen['controls']][:18],flush=True)
    if slug=='dev-lead': names=['小さくする','大きくする','全体','全部開く','細部を閉じる']
    elif slug=='fukurou-inbox': names=['契約前','契約後','見送り','すべて','設定']
    else: names=['ふくろうP @FukurouKantoku','ポルノアンチ @PornoAnti_JP','本田樹 @OYmpa7','ふくろうP @FukurouKantoku','本田樹 @OYmpa7']
    for name in names:
     screen=C.current(stage)
     control=next((c for c in screen['controls'] if c['name']==name),None)
     if not control: raise AssertionError(slug+': missing '+name)
     prior=screen.get('text','');start=time.perf_counter()
     out=await C.operate(stage,'click',control['id'],page_id=screen['page_id'],fingerprint=control['fingerprint'])
     # Unknown buttons remain guarded. This test only exercises the read-only controls listed above.
     if out.get('requires_approval'):
      stage.dialogue.add('assistant',out['read_back']);stage.dialogue.add('user','いいよ')
      out=await C.operate(stage,'click',control['id'],page_id=screen['page_id'],fingerprint=control['fingerprint'])
     assert out.get('ok'),(slug,name,out)
     ms=round((time.perf_counter()-start)*1000)
     await asyncio.sleep(.7)
     frame=page.frames[1]
     # Visible UI state is measured independently of the command receipt.
     if slug=='fukurou-inbox' and name!='設定':
      assert await frame.get_by_role('tab',name=name,exact=True).get_attribute('aria-selected')=='true'
     elif slug=='x-operation':
      assert await frame.get_by_role('tab',name=name,exact=True).get_attribute('aria-selected')=='true'
     elif slug=='fukurou-inbox':
      await frame.get_by_text('契約書・請求書の設定',exact=True).wait_for(timeout=10000)
     elif name=='全部開く': assert await frame.get_by_role('button',name='細部を閉じる',exact=True).count()
     elif name=='細部を閉じる': assert await frame.get_by_role('button',name='全部開く',exact=True).count()
     report['operations'].append({'site':slug,'control':name,'command_to_receipt_ms':ms,'ok':True})
     print(name,ms,flush=True)
    await page.screenshot(path=str(proof/(slug+'-after.png')))
    stage.close();await page.close()
  finally:
   (proof/'operations.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
   await context.close();await browser.close()
 tmp.cleanup()
 print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':asyncio.run(main())
