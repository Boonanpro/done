"""Read-only memo UI verification; never starts an audio session."""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    out=Path('scratch/upstream-consultation-20260922');out.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        page=await browser.new_page(viewport={'width':1440,'height':960})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        await page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
        await page.locator('#consultation-inspector').wait_for()
        await page.evaluate("""()=>{
          context={room_id:'inspector-test',content_id:'film-test'};
          localStorage.setItem(consultationMemoKey({editContext:context}),JSON.stringify({version:3,
            fields:{video_type:{status:'confirmed',value:'映画'},subject:{status:'confirmed',value:'自宅の作業場で航空機を開発する物語'},purpose:{status:'confirmed',value:'自分で見たい作品'}}}));
        }""")
        await page.wait_for_function("()=>document.querySelector('#consultation-inspector').textContent.includes('航空機')")
        assert await page.locator('#consultation-inspector dd[data-known=false]').count()==5
        await page.screenshot(path=str(out/'consultation-inspector.png'))
        await page.evaluate("""()=>{
          const key=consultationMemoKey({editContext:context}),memo=JSON.parse(localStorage.getItem(key));
          for(const field of ['platform','audience','duration','materials','references'])memo.fields[field]={status:'undecided',value:'下書きを見て決める'};
          memo.reference_agreed=true;memo.ready_for_draft=true;localStorage.setItem(key,JSON.stringify(memo));
        }""")
        await page.wait_for_function("()=>document.querySelector('#consultation-inspector').textContent.includes('下書きへ進む相談')")
        assert await page.locator('#consultation-inspector dd[data-known=false]').count()==0
        await page.evaluate("context={room_id:'inspector-test',content_id:'another-work'}")
        await page.wait_for_function("()=>!document.querySelector('#consultation-inspector').textContent.includes('航空機')")
        assert await page.locator('#consultation-inspector dd[data-known=false]').count()==8
        await page.locator('#show-consultation').click()
        assert not await page.locator('#consultation-inspector').is_visible()
        await page.locator('#show-consultation').click()
        await page.set_viewport_size({'width':390,'height':844})
        box=await page.locator('#consultation-inspector').bounding_box()
        assert box['x']>=0 and box['x']+box['width']<=390
        await page.screenshot(path=str(out/'consultation-inspector-mobile.png'))
        assert not errors,errors
        print(json.dumps({'live_page':True,'memo_updates':True,'project_isolation':True,'toggle':True,'mobile_fits':True,'page_errors':errors}))
        await browser.close()

if __name__=='__main__':asyncio.run(main())
