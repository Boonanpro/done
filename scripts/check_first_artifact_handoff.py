"""Execute the real model-selected image handoff through the editor browser."""
import asyncio,json,time
from pathlib import Path
from playwright.async_api import async_playwright
from app.services import timeline_draft as td

async def main():
 out=Path('scratch/first-artifact-milestone')
 decision=json.loads((out/'appearance.json').read_text(encoding='utf8'))
 args=next(c['args'] for t in decision['turns'] for c in t['calls'] if c['name']=='run_editor_task')
 room=decision['room'];cid=decision['content_id']
 with td.ContentsLock(room):
  contents=td._read_contents_raw(room)
  content=td._find_content(contents,cid)
  content.setdefault('timeline',{'format':'16:9','sequence':{'format':'16:9','duration':0,'frame_rate':30,'tracks':[]}})
  td._write_contents_raw(room,contents)
 started=time.perf_counter()
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True)
  page=await browser.new_page(viewport={'width':1440,'height':1000})
  try:
   await page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
   await page.evaluate('v=>window.__setEditorAuth(v)',{'token':(Path.home()/'.done/native_token.txt').read_text().strip()})
   await page.evaluate('c=>{context=c}',{'room_id':room,'content_id':cid,'playhead':0,'selected':[]})
   await page.evaluate('rows=>{conversationMemory.splice(0,conversationMemory.length,...rows)}',[
    {'role':'user','text':'自宅の作業場で翼付き自動車を開発する男の30秒の映画予告を作りたい。写実的な方向は良いけど、見た目はまだぼんやりしてる。'},
    {'role':'assistant','text':decision['turns'][0]['text']},
    {'role':'user','text':'うん。それで進めて。今回提案してくれた見本に必要な生成費用も使っていいよ。'}])
   result=await page.evaluate('''args=>executeLiveConsultationTool(
     {name:'run_editor_task',call_id:'handoff-check',arguments:JSON.stringify(args)},
     {id:'handoff-check',editContext:context},context)''',args)
   print('accepted',result,flush=True)
   while time.perf_counter()-started<360:
    content=td._find_content(td._read_contents_raw(room),cid) or {}
    if content.get('look_frames'):
     await page.evaluate('p=>renderReferences(p)',content['presentation'])
     await page.wait_for_function('()=>[...document.querySelectorAll(".reference-card img")].some(i=>i.complete&&i.naturalWidth>0)',timeout=20000)
     await page.screenshot(path=str(out/'appearance-browser.png'))
     report={'seconds':round(time.perf_counter()-started,2),'look_frames':content['look_frames'],'timeline':content.get('sequence'),'accepted':result}
     (out/'appearance-handoff.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
     print('image saved and displayed',report['seconds'],flush=True)
     # Let the current reasoning response finish before closing this test page.
     await page.wait_for_function('()=>!reasonRunning',timeout=90000)
     return
    await asyncio.sleep(2)
   raise TimeoutError('No look frame within six minutes; inspect isolated project job logs')
  finally:await browser.close()

if __name__=='__main__':asyncio.run(main())
