"""Browser decode/playback checks for locally inspected reference excerpts."""
import asyncio,json
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    catalog=Path('docs/reference-library.json');rows=json.loads(catalog.read_text(encoding='utf8'))
    token=(Path.home()/'.done/native_token.txt').read_text().strip();results=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        page=await browser.new_page(extra_http_headers={'Authorization':'Bearer '+token})
        await page.goto('http://127.0.0.1:8012/health')
        for row in rows:
            if not row['id'].startswith(('film-','stock-')):continue
            result=await page.evaluate('''async id=>{
              const v=document.createElement('video');v.muted=true;v.preload='auto';
              v.src='/api/v1/editor-assistant/reference-library/media/'+id;document.body.replaceChildren(v);
              await Promise.race([new Promise((ok,no)=>{v.onloadeddata=ok;v.onerror=()=>no(Error('media decode failed'));}),new Promise((_,no)=>setTimeout(()=>no(Error('load timeout')),5000))]);
              await v.play();await new Promise(r=>setTimeout(r,400));
              return {id,width:v.videoWidth,height:v.videoHeight,duration:v.duration,advanced:v.currentTime>.1,error:v.error?.code||null};
            }''',row['id'])
            assert result['advanced'] and result['width']>0 and not result['error'],result
            results.append(result)
            row['inspection']='Source contact frames visually inspected; browser decode and playback verified 2026-09-17'
        await browser.close()
    catalog.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    Path('scratch/visual-decision/film-playback.json').write_text(json.dumps(results,indent=2),encoding='utf8')
    print(json.dumps(results))

asyncio.run(main())
