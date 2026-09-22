"""Browser-level regression tests for notification and mixed-input state."""
import os
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page()
    page.add_init_script('window.setInterval=()=>0;')
    page.goto('http://127.0.0.1:'+os.getenv('EDITOR_TEST_PORT','8027')+'/api/v1/editor-assistant/page')
    page.evaluate("""()=>{
      context={room_id:'transport-test',content_id:'test'};
      window.sent=[];dc={readyState:'open',send:text=>sent.push(JSON.parse(text))};
      turn={mode:'text'};micOn=true;respond();
    }""")
    assert page.evaluate("sent.at(-1).response.output_modalities[0]==='audio'")
    page.evaluate("active=false;micOn=false;turn.mode='voice';respond();")
    assert page.evaluate("sent.at(-1).response.output_modalities[0]==='text'")
    page.evaluate("""async()=>{
      activeNotice={transcript:'変更しました。'};error(Error('old protocol error'));
      await onEvent({type:'response.done',response:{status:'completed'}});
    }""")
    assert page.evaluate("sent.at(-1).item.content[0].type==='output_text'")
    assert page.locator('#toast').inner_text()==''
    page.evaluate("""()=>{
      micOn=true;speech={};jobs.set('job',{});
      renderProductionStatus({jobs:[{id:'job',status:'done',result:{committed:true,summary:'完了'}}]},context);
      announceCompletion();
    }""")
    assert page.evaluate("completionNotices.length===1&&!active")
    page.evaluate("speech=null;announceCompletion();")
    assert page.evaluate("activeNotice.job_id==='job'&&active")
    page.evaluate("""async()=>{
      turn=null;await interrupt();
    }""")
    assert page.evaluate("completionNotices.length===1&&!audioPlaying&&!active")
    page.evaluate("""()=>{
      completionNotices.length=0;activeNotice=null;busy=false;
      jobs.set('old',{});jobs.set('new',{});
      renderProductionStatus({jobs:[
        {id:'old',status:'done',created_at:'2026-09-08T01:00:00',updated_at:'2026-09-08T01:01:00',result:{}},
        {id:'new',status:'running',created_at:'2026-09-08T01:02:00',result:{}}
      ]},context);
    }""")
    assert page.evaluate("!completionNotices.some(n=>n.job_id==='old')")
    assert page.locator('.production-card').count()==1
    browser.close()
print('PASS mixed input audio, assistant replay, error recovery, notification interrupt/retry, stale notices, active cards')
