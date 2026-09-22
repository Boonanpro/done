"""Decode actual authored frames, check seeking, and build a local review."""
import asyncio, hashlib, html, json, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'scratch/component-creative-cycle'

async def main(render=False):
 from playwright.async_api import async_playwright
 from PIL import Image,ImageDraw,ImageChops,ImageStat
 import io
 import imageio_ffmpeg
 results=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True)
  for file in [OUT/(i+'.html') for i in ['a','b','c','revised'] if (OUT/(i+'.html')).exists()]:
   page=await browser.new_page(viewport={'width':1920,'height':1080},device_scale_factor=.5)
   errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   started=time.perf_counter();await page.goto(file.as_uri())
   try:await page.wait_for_function('!!window.__timelines?.sample',timeout=5000)
   except Exception:
    print(json.dumps({'file':file.name,'errors':errors,'state':await page.evaluate('({url:location.href,gsap:typeof gsap,html:document.documentElement.outerHTML.slice(0,700),scripts:document.scripts.length})')}));raise
   await page.evaluate('document.fonts.ready');await page.evaluate('()=>{window.__timelines.sample.seek(1)}')
   await page.screenshot();display_ms=round((time.perf_counter()-started)*1000)
   sheet=Image.new('RGB',(960*2,540*3),'#222');draw=ImageDraw.Draw(sheet)
   for j,t in enumerate([1.5,3.4,5.2,6.8,8.4,9.8]):
    await page.evaluate('(t)=>{window.__timelines.sample.seek(t)}',t)
    target=OUT/(file.stem+f'-{t}.png');await page.screenshot(path=str(target))
    with Image.open(target) as im:sheet.paste(im,(j%2*960,j//2*540))
   sheet.save(OUT/(file.stem+'-contact.jpg'))
   # Arbitrary backward seeks must reproduce the same frame.
   await page.evaluate('()=>{window.__timelines.sample.seek(3.4)}');first=await page.screenshot()
   await page.evaluate('()=>{window.__timelines.sample.seek(9.8);window.__timelines.sample.seek(3.4)}');second=await page.screenshot()
   exact=hashlib.sha256(first).digest()==hashlib.sha256(second).digest()
   diff=ImageChops.difference(Image.open(io.BytesIO(first)),Image.open(io.BytesIO(second)))
   delta=max(hi for lo,hi in diff.getextrema());mean=max(ImageStat.Stat(diff).mean)
   # Browser gradient antialiasing may differ by one channel value at a few pixels.
   deterministic=exact or (delta<=1 and mean<.001)
   body=await page.locator('body').inner_text()
   result={'id':file.stem,'display_ms':display_ms,'errors':errors,'seek_deterministic':deterministic,'seek_pixel_exact':exact,'seek_max_channel_delta':delta,'seek_mean_delta':mean,'closing_count':await page.locator('#closing-copy').count(),'text':body}
   assert deterministic and not errors,result
   results.append(result);print(json.dumps(result,ensure_ascii=True),flush=True)
   if render and not ('--missing' in sys.argv and (OUT/(file.stem+'.mp4')).exists()):
    dest=OUT/(file.stem+'.mp4')
    proc=subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-loglevel','error','-f','image2pipe','-vcodec','png','-r','30','-i','-','-an','-c:v','libx264','-pix_fmt','yuv420p','-crf','18','-movflags','+faststart',str(dest)],stdin=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    for n in range(300):
     await page.evaluate('(t)=>{window.__timelines.sample.seek(t)}',n/30)
     frame=await page.screenshot();await asyncio.to_thread(proc.stdin.write,frame)
    proc.stdin.close();await asyncio.to_thread(proc.wait)
    if proc.returncode:raise RuntimeError(proc.stderr.read().decode())
   await page.close()
  await browser.close()
 (OUT/'visual-checks.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 plan=json.loads((OUT/'plan.json').read_text(encoding='utf-8'))
 names={d['id']:d['title'] for d in plan['directions']};names['revised']='修正後'
 cards=[]
 for r in results:
  if (OUT/(r['id']+'.mp4')).exists():cards.append('<article><h2>'+html.escape(names[r['id']])+'</h2><video controls preload="metadata" poster="'+r['id']+'-1.5.png" src="'+r['id']+'.mp4"></video></article>')
 (OUT/'review.html').write_text('''<!doctype html><html lang="ja"><meta charset="utf-8"><title>Dan・3つの演出</title><style>body{margin:32px;background:#141619;color:#eee;font-family:Meiryo,sans-serif}h1{font-size:24px}h2{font-size:16px;font-weight:500}main{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:28px}video{width:100%;border-radius:10px}p{color:#aab0b9;font-size:13px}@media(max-width:800px){main{grid-template-columns:1fr}}</style><h1>話しながら、映像に。</h1><p>同じ目的から作った10秒の演出比較・無音。元の参考動画の転載ではなく、部品のコードを改変した制作物です。</p><main>'''+''.join(cards)+'''</main><script>document.querySelectorAll('video').forEach(v=>v.addEventListener('play',()=>document.querySelectorAll('video').forEach(o=>{if(o!==v)o.pause()})))</script></html>''',encoding='utf-8')

if __name__=='__main__':asyncio.run(main('--render' in sys.argv))
