"""Decode and play every imported preview, capture start/middle/end for review."""
import asyncio,json,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'scratch/component-expansion';OUT.mkdir(parents=True,exist_ok=True)

async def main():
 from playwright.async_api import async_playwright
 from PIL import Image,ImageDraw
 manifest=ROOT/'docs/component-library.json';rows=json.loads(manifest.read_text(encoding='utf-8'))
 pagefile=OUT/'inspect.html';pagefile.write_text('<!doctype html><style>body{margin:0;background:#101820}video{width:960px;height:540px;object-fit:contain}</style><video muted playsinline></video>',encoding='utf-8')
 results=[];panels=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True);page=await browser.new_page(viewport={'width':960,'height':540});await page.goto(pagefile.as_uri())
  for row in rows:
   if '--new-only' in sys.argv and row.get('inspection')!='pending':continue
   try:
    media=ROOT/'uploads/reference-library'/(row['id']+'.mp4')
    assert hashlib.sha256(media.read_bytes()).hexdigest()==row['sha256']
    for entry in row['files']:
     assert hashlib.sha256((ROOT/'app/data/component-library'/row['component']/entry['file']).read_bytes()).hexdigest()==entry['sha256']
    info=await page.evaluate('''async url=>{const v=document.querySelector('video');v.pause();v.src=url;await new Promise((ok,no)=>{v.onloadeddata=ok;v.onerror=()=>no(Error('decode failed'));setTimeout(()=>no(Error('media timeout')),10000)});return {duration:v.duration,width:v.videoWidth,height:v.videoHeight};}''',media.as_uri())
    assert info['duration']>0 and info['width']>0
    await page.evaluate("document.querySelector('video').play()");await page.wait_for_timeout(220);assert await page.evaluate("document.querySelector('video').currentTime")>.08
    await page.evaluate("document.querySelector('video').pause()")
    panel=Image.new('RGB',(960,205),'#101820');draw=ImageDraw.Draw(panel);draw.text((8,5),row['id'],fill='white')
    for n,fraction in enumerate([.15,.5,.85]):
     await page.evaluate('''async t=>{const v=document.querySelector('video');await new Promise(ok=>{v.onseeked=ok;v.currentTime=t});}''',info['duration']*fraction)
     shot=OUT/(row['id']+f'-{n}.png');await page.screenshot(path=str(shot));im=Image.open(shot);im.thumbnail((320,180));panel.paste(im,(n*320,25))
    panels.append(panel);row['inspection']='decoded; playback advanced; frames captured at 15/50/85%; see component-expansion review';row['measured']=info;results.append({'id':row['id'],'ok':True,**info})
   except Exception as e:
    row['inspection']='pending';results.append({'id':row['id'],'ok':False,'error':str(e)})
   print(json.dumps(results[-1]),flush=True)
  await browser.close()
 for index in range(0,len(panels),6):
  sheet=Image.new('RGB',(960,205*len(panels[index:index+6])),'#101820')
  for j,panel in enumerate(panels[index:index+6]):sheet.paste(panel,(0,j*205))
  sheet.save(OUT/f'{"new-" if "--new-only" in sys.argv else ""}contact-{index//6+1}.jpg')
 manifest.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');(OUT/('new-verification.json' if '--new-only' in sys.argv else 'verification.json')).write_text(json.dumps(results,indent=2),encoding='utf-8')

if __name__=='__main__':asyncio.run(main())
