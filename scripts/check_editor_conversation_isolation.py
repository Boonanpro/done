"""Read-only production UI regression; no microphone or model calls."""
import asyncio,json
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    out=Path('scratch/editor-conversation-fix');out.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        page=await browser.new_page(viewport={'width':1100,'height':800})
        await page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
        await page.wait_for_function('typeof window.__updateEditorContext === "function"')
        result=await page.evaluate('''() => {
          const room='isolation-browser-test';
          localStorage.setItem('editor-conversation:'+room,JSON.stringify({content_id:'A',messages:[{role:'user',text:'legacy A'}]}));
          window.__updateEditorContext({room_id:room,content_id:'B',playhead:0});
          if(conversationMemory.length)throw Error('Legacy A leaked into B');
          conversationMemory.push({role:'user',text:'B movie'});saveConversation();
          window.__updateEditorContext({room_id:room,content_id:'A',playhead:0});
          if(conversationMemory.length!==1||conversationMemory[0].text!=='legacy A')throw Error('A restore failed');
          window.__updateEditorContext({room_id:room,content_id:'B',playhead:0});
          if(conversationMemory.length!==1||conversationMemory[0].text!=='B movie')throw Error('B restore failed');
          liveConnection={started:true,editContext:structuredClone(context),rows:{},views:[],work:{status:'running',detail:'参考の映像を探しています'}};
          busy=true;updatePresence();
          const line=document.getElementById('orb-status').textContent;
          if(line!=='参考の映像を探しています')throw Error('Missing visible work line');
          return {legacy_isolated:true,reopen_restored:true,work_line:line};
        }''')
        await page.screenshot(path=str(out/'presence.png'))
        (out/'browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(result,ensure_ascii=False));await browser.close()

asyncio.run(main())
