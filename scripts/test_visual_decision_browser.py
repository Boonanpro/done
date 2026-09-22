"""Real Jev + actual editor delegation path. Transcript injection, not audio latency."""
import asyncio,json,sys,uuid,time,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from playwright.async_api import async_playwright

UTTERANCES=[
 '字幕は落ち着いた感じにしたい。まだどんな見た目がいいか分からない。',
 'もっと上品で、文字がゆっくり現れる方が近い。',
 '明朝体で一部分だけ金色になるものが一番近い。',
 '今度は別の動画。コードが組み上がって完成するような動きを比較したい。',
 '文字だけより、コードが粒になって集まる見せ方が近い。',
 '新しい案。地図で世界へ広がるサービスを紹介する動きを見たい。',
 '地図上の複数の場所が線で結ばれるような感じ。',
 '別の字幕を考えたい。元気で勢いがあって、文字がドンと出る感じ。',
 '文字が何層にも重なるより、一発で大きく出る方がいい。',
]

async def main():
 from app.services import timeline_draft as td
 out=Path(os.environ.get('DAN_TEST_OUTPUT','scratch/visual-decision'));out.mkdir(parents=True,exist_ok=True)
 room='visual-decision-'+uuid.uuid4().hex[:8];cid='test';folder=td._room_dir(room);folder.mkdir(parents=True)
 (folder/'contents.json').write_text(json.dumps([{'id':cid,'timeline':{'sequence':{'duration':0,'tracks':[]}}}]))
 token=(Path.home()/'.done/native_token.txt').read_text().strip()
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True);page=await browser.new_page(viewport={'width':1440,'height':1000})
  await page.goto(os.environ.get('DAN_TEST_BASE','http://127.0.0.1:8012')+'/api/v1/editor-assistant/page')
  await page.wait_for_function('typeof liveDelegate === "function" && typeof context!=="undefined"')
  await page.evaluate('''({token,room,cid})=>{
    window.__editorBootstrap={token};window.__updateEditorContext({room_id:room,content_id:cid,playhead:0,selected:[]});
    liveConnection={started:true,startedAt:Date.now(),id:'test',editContext:structuredClone(context),rows:{},views:[]};
    dc={readyState:'open',send:()=>{}};micOn=true;
    window.testBackendCalls=0;runReasoning=async()=>{window.testBackendCalls++;setBusy(false);};
    window.testEvents=[];const originalRecord=record;record=(type,data)=>{window.testEvents.push({type,...data});originalRecord(type,data);};
  }''',{'token':token,'room':room,'cid':cid})
  results=[]
  for n,text in enumerate(UTTERANCES):
   result=await page.evaluate('''async text=>{
     const before=performance.now(), prior=window.testBackendCalls;
     conversationMemory.push({role:'user',text});liveConnection.rows.user={id:crypto.randomUUID(),text,views:[]};
     const first=window.testEvents.length;liveDelegate({delegation:{id:crypto.randomUUID()}},liveConnection);await liveTaskQueue;
     const events=window.testEvents.slice(first),shown=events.find(e=>e.type==='reference_library_displayed');
     const decision=events.find(e=>e.type==='visual_decision');
     const latest=Array.from(presentationFeed.values()).at(-1);
     if(shown&&latest)conversationMemory.push({role:'assistant',text:'表示した候補: '+JSON.stringify(latest.items.map(i=>({title:i.title,library_id:i.library_id})))});
     return {elapsed_ms:Math.round(performance.now()-before),displayed:!!shown,decision,backend_calls:window.testBackendCalls-prior,items:latest?.items.map(i=>({id:i.id,title:i.title,library_id:i.library_id})),errors:events.filter(e=>e.type.includes('error'))};
   }''',text)
   results.append({'utterance':text,**result});print(json.dumps(results[-1],ensure_ascii=False),flush=True)
   await page.screenshot(path=str(out/f'browser-{n+1}.png'))
   (out/'browser-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
  await browser.close()
 print('room',room)

asyncio.run(main())
