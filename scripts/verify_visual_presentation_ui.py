"""Real browser checks: consistent comparison widths and visible motion playback."""
import asyncio,json,uuid
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        page=await browser.new_page(viewport={'width':1440,'height':1000})
        await page.goto('http://127.0.0.1:8012/api/v1/editor-assistant/page')
        await page.evaluate('v=>window.__setEditorAuth(v)',{'token':token})
        await page.evaluate('''()=>{
          context={room_id:'ui-test',content_id:'test'};
          const item=(id)=>({id,title:id,kind:'video',library_id:'film-sintel-dialogue',url:'/api/v1/editor-assistant/reference-library/media/film-sintel-dialogue'});
          appendPresentation({id:'two',at:1,items:[item('one'),item('two')]});
          appendPresentation({id:'single',at:2,items:[item('three')]});
        }''')
        await page.wait_for_function('()=>document.querySelector("[data-item-id=three] video").currentTime>.2')
        result=await page.evaluate('''async()=>{
          const widths=[...document.querySelectorAll('.reference-card')].map(e=>e.getBoundingClientRect().width);
          const card=document.querySelector('[data-item-id=three]'),v=card.querySelector('video');
          const autoplay=!v.paused&&v.muted&&v.currentTime>.2;
          await card.querySelector('.proposal-player').control('pause');
          return {widths,autoplay,paused:v.paused};
        }''')
        assert max(result['widths'])-min(result['widths'])<1,result
        assert result['autoplay'] and result['paused'],result
        await page.wait_for_timeout(800)
        assert await page.locator('[data-item-id=three] video').evaluate('(v)=>v.paused')
        await page.evaluate('''async()=>{
          await livePresentationAction({...context,live_dialogue:[]},{rows:{}},'inspect',()=>true,
            {handled:true,action:'reveal',item_id:'three',destination:'viewer'});
        }''')
        assert await page.locator('dialog[open] [data-proposal-item-id=three]').count()==1
        result['viewer_opened']=True
        await page.evaluate('''async()=>{
          await livePresentationAction({...context,live_dialogue:[]},{rows:{}},'pause',()=>true,
            {handled:true,action:'pause',item_id:'three',destination:'viewer'});
        }''')
        assert await page.locator('dialog[open] video').evaluate('(v)=>v.paused')
        await page.locator('dialog[open] .proposal-close').click()
        await page.evaluate('''()=>{
          const prior=presentationFeed.get('single'),item=prior.items[0];
          appendPresentation({...prior,revision:2,items:[{...item,id:'four'}]});
          appendPresentation({...prior,revision:1});
        }''')
        assert await page.locator('[data-presentation=single]').count()==1
        assert await page.locator('[data-item-id=four]').count()==1
        assert await page.locator('[data-item-id=three]').count()==0
        result['one_group_per_utterance']=True;result['stale_history_ignored']=True
        await page.screenshot(path='scratch/visual-decision/presentation-ui.png')
        Path('scratch/visual-decision/presentation-ui.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result));await browser.close()

asyncio.run(main())
