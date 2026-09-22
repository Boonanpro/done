"""Actual Jev search and presentation through the new Live tool adapter."""
import asyncio,json
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    out=Path('scratch/live-consultation-sheet');out.mkdir(parents=True,exist_ok=True)
    Path('uploads/production-assets/sheet-reference-test').mkdir(parents=True,exist_ok=True)
    contents=Path('uploads/production-assets/sheet-reference-test/contents.json')
    if not contents.exists():contents.write_text(json.dumps([{'id':'sheet-reference-test','title':'Reference tool verification'}]),encoding='utf-8')
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        page=await browser.new_page(viewport={'width':1440,'height':1000})
        await page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
        await page.evaluate('v=>window.__setEditorAuth(v)',{'token':token})
        result=await page.evaluate('''async()=>{
          context={room_id:'sheet-reference-test',content_id:'sheet-reference-test'};
          const session={id:'sheet-reference-test',editContext:structuredClone(context),rows:{}};
          const result=await executeLiveConsultationTool({name:'search_reference_library',call_id:crypto.randomUUID(),arguments:JSON.stringify({query:'宇宙や科学の謎をわかりやすく解説するYouTube動画の参考。科学解説チャンネルの全体の見せ方を比較したい。',scope:'work'})},session,structuredClone(context));
          return {result,cards:document.querySelectorAll('.reference-card').length,sheet:readConsultationMemo(session)};
        }''')
        assert result['cards']>0,result
        assert result['sheet'] is None,result
        await page.wait_for_timeout(3000)
        await page.screenshot(path=str(out/'references.png'))
        (out/'reference-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'cards':result['cards'],'shown':result['result'].get('shown'),'ms':result['result'].get('search_ms'),'sheet_unchanged':True}))
        await browser.close()

if __name__=='__main__':asyncio.run(main())
