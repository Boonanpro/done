"""Real page + create/delete APIs; optional real Live silent reconnection check."""
import asyncio
import json
import sys
import uuid
from pathlib import Path
from playwright.async_api import async_playwright


async def main():
    room='conversation-lifecycle-'+uuid.uuid4().hex[:10]
    folder=Path('uploads/production-assets')/room
    folder.mkdir(parents=True)
    out=Path('scratch/conversation-lifecycle-20260923');out.mkdir(parents=True,exist_ok=True)
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        page=await browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
        await page.evaluate('v=>window.__setEditorAuth(v)',{'token':token})
        try:
            a=await page.evaluate('async room=>(await api("/new",{room_id:room})).content_id',room)
            await page.evaluate('''c=>{
              window.__updateEditorContext(c);
              conversationMemory.push({role:'user',text:'Old project reference'});saveConversation();
              localStorage.setItem(consultationMemoKey({editContext:c}),JSON.stringify({version:2,instruction:'Resume old work'}));
              renderReferences({id:'old-reference',items:[{id:'old',kind:'text',title:'Old reference',text:'OLD PROJECT'}]});
              livePausedContext=structuredClone(c);
            }''',{'room_id':room,'content_id':a})
            await page.screenshot(path=str(out/'before-delete.png'))
            response=await page.request.delete(f'http://127.0.0.1:8000/api/v1/production-assets/contents/{a}?room_id={room}',headers={'Authorization':'Bearer '+token})
            assert response.ok,await response.text()
            await page.evaluate('()=>reconcileConversationProjects()')
            b=await page.evaluate('async room=>(await api("/new",{room_id:room})).content_id',room)
            result=await page.evaluate('''c=>{
              pendingNewId=c.content_id;window.__updateEditorContext(c);
              return {messages:conversationMemory.length,references:presentationFeed.size,
                memo:readConsultationMemo({editContext:c}),paused:livePausedContext,
                oldKeys:Object.keys(localStorage).filter(k=>k.includes(c.old))};
            }''',{'room_id':room,'content_id':b,'old':a})
            assert result=={'messages':0,'references':0,'memo':None,'paused':None,'oldKeys':[]},result
            await page.wait_for_timeout(600)
            await page.screenshot(path=str(out/'new-project.png'))
            assert await page.locator('#consultation-inspector dd[data-known=false]').count()==8
            result['silent_connections']=[]
            if '--live' in sys.argv:
                # Exercise the actual connection handler, without attaching any
                # microphone. Both fresh and history-bearing sessions should wait.
                for history in [[],[{'role':'user','text':'参考を出してくれたけど、どういうものか説明して。'},
                                     {'role':'assistant','text':'二つの参考を比べてみましょう。'}]]:
                    await page.evaluate('''history=>{
                      conversationMemory.length=0;conversationMemory.push(...history);
                      window.probeEvents=[];window.probeRecord=record;
                      record=(type,data)=>{window.probeEvents.push({type,...data});window.probeRecord(type,data);};
                    }''',history)
                    await page.evaluate('()=>connectLive()')
                    await page.wait_for_timeout(15000)
                    events=await page.evaluate('()=>window.probeEvents')
                    spoken=[e for e in events if e['type'] in ['assistant_transcript','voice_output_started']]
                    result['silent_connections'].append({'history_rows':len(history),'spontaneous_outputs':spoken})
                    await page.evaluate('()=>{disconnect("test_complete");record=window.probeRecord;}')
                    await page.wait_for_timeout(1200)
                assert all(not c['spontaneous_outputs'] for c in result['silent_connections']),result
            assert not errors,errors
            result['page_errors']=errors
            (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False))
        finally:
            await page.evaluate('()=>disconnect("test_cleanup")')
            await browser.close()


if __name__=='__main__':asyncio.run(main())
