"""Actual Realtime completion speech; no user timeline or microphone is touched."""
import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(bypass_csp=True)
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    page.goto('http://127.0.0.1:'+os.getenv('EDITOR_TEST_PORT','8012')+'/api/v1/editor-assistant/page')
    page.evaluate('flushAudit=async()=>{}')
    page.evaluate('async()=>{await connect();context={room_id:"ui-only",content_id:"ui-only"};}')
    page.evaluate('()=>{window.responseCalls=[];const originalSend=send;send=e=>{if(e.type==="response.create")responseCalls.push(e);originalSend(e);};}')
    # Empty transcription must not begin a turn or produce a response.
    page.evaluate('async()=>{pendingTranscripts.set("cough","");await startSpeech("cough");await stopSpeech();}')
    assert page.evaluate('audit.some(e=>e.type==="non_speech_ignored")&&!audit.some(e=>e.type==="utterance_started")')
    fake={'jobs':[{'id':'notification-test','status':'running','request':'背景4カットを白黒の昭和レトロな映像に変更する','activity':[{'tool':'generate_video','state':'running','category':'generation','model':'gemini_omni_flash_1_1'}]}],
          'work':[{'id':'heygen','status':'blocked','title':'HeyGen'}]}
    page.evaluate('(s)=>renderProductionStatus(s,context)',fake)
    assert page.locator('.production-card').count()==1
    page.evaluate('micOn=true;speech={};')
    fake['jobs'][0].update(status='done',result={'committed':True})
    page.evaluate('(s)=>{renderProductionStatus(s,context);announceCompletion();}',fake)
    assert page.locator('.production-card').count()==0
    assert page.evaluate('completionNotices.length===1&&!active')
    page.evaluate('speech=null;announceCompletion();')
    page.wait_for_function('audit.some(e=>e.type==="assistant_transcript")',timeout=45000)
    spoken=page.evaluate('audit.filter(e=>e.type==="assistant_transcript").map(e=>e.text)')
    print('SPOKEN',json.dumps(spoken,ensure_ascii=False))
    page.evaluate('(s)=>renderProductionStatus(s,context)',fake)
    assert page.evaluate('responseCalls.length===1')
    assert page.evaluate('!audit.some(e=>e.type==="tool_started")')
    page.evaluate('disconnect();');browser.close()
print('PASS empty utterance ignored, only active cards, voice completion deferred during speech, one announcement')
