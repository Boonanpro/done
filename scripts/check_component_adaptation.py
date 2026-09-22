"""Prove imported source is editable, not only a collected MP4."""
import asyncio,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'scratch/component-expansion/adapted';OUT.mkdir(parents=True,exist_ok=True)

async def main():
 import httpx
 from playwright.async_api import async_playwright
 vendor=OUT/'gsap.min.js'
 if not vendor.exists():
  async with httpx.AsyncClient(timeout=30) as c:
   r=await c.get('https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js');r.raise_for_status();vendor.write_bytes(r.content)
 names=['data-chart','caption-pill-karaoke'];results=[]
 for name in names:
  source=(ROOT/'app/data/component-library'/name/(name+'.html')).read_text(encoding='utf-8')
  source=re.sub(r'<link\b[^>]*>','',source,flags=re.S)
  source=source.replace('https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js','gsap.min.js')
  if name=='data-chart':
   source=source.replace('Monthly Revenue vs. Conversion Rate','月別の売上と成約率（架空データ）').replace('Jan–Jun 2024, in thousands','編集可能な元ソースを使った検証')
   source=source.replace('["Jan", "Feb", "Mar", "Apr", "May", "Jun"]','["1月", "2月", "3月", "4月", "5月", "6月"]')
   source=source.replace('[8, 12, 15, 11, 18, 22]','[5, 9, 7, 16, 20, 24]')
  else:
   transcript=[{'text':word,'start':i*.8,'end':(i+1)*.8} for i,word in enumerate(['思い描いた','映像を、','話しながら','形に。','ここだけ','直して、','続きを','作ろう。'])]
   source=re.sub(r'var TRANSCRIPT = \[.*?\];','var TRANSCRIPT = '+json.dumps(transcript,ensure_ascii=False)+';',source,flags=re.S)
   source=source.replace('var FONT_FAMILY = "Poppins"','var FONT_FAMILY = "Yu Gothic"')
  source=source.replace('</head>','<style>body{background:#101820}#data-chart{background:#faf9f6}*{font-family:"Yu Gothic",Meiryo,sans-serif!important}</style></head>')
  source=source.replace('</body>','<script>document.addEventListener("click",()=>Object.values(window.__timelines||{}).forEach(t=>t.paused(!t.paused())));setTimeout(()=>Object.values(window.__timelines||{}).forEach(t=>t.repeat(-1).play()),100);</script></body>')
  (OUT/(name+'.html')).write_text(source,encoding='utf-8')
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True)
  for name in names:
   page=await browser.new_page(viewport={'width':1920,'height':1080});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   await page.goto((OUT/(name+'.html')).as_uri());await page.wait_for_function('Object.keys(window.__timelines||{}).length>0')
   await page.evaluate('Object.values(window.__timelines).forEach(t=>t.pause())')
   for t in [1.6,3.5,6]:
    await page.evaluate('(s)=>Object.values(window.__timelines).forEach(t=>t.seek(s))',t);await page.screenshot(path=str(OUT/(name+f'-{t}.png')))
   body=await page.locator('body').inner_text();assert ('架空データ' if name=='data-chart' else '思い描いた') in body
   assert not errors,errors;results.append({'id':name,'japanese_content':True,'errors':errors});await page.close()
  await browser.close()
 (OUT/'results.json').write_text(json.dumps(results,indent=2));print(json.dumps(results))

if __name__=='__main__':asyncio.run(main())
