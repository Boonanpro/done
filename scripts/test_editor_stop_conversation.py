"""Actual Realtime chooses production stop while preserving the voice connection."""
import json,time,uuid
from pathlib import Path
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
room='stop-conversation-'+uuid.uuid4().hex[:8];folder=root/'uploads/production-assets'/room
folder.mkdir(parents=True)
content={'id':'test','title':'停止の動作確認','timeline':{'sequence':{'duration':1,'format':'16:9','tracks':[]}}}
(folder/'contents.json').write_text(json.dumps([content]),encoding='utf-8')
(folder/'assets.json').write_text('[]')
(folder/'jobs.json').write_text(json.dumps([{'id':'test-job','content_id':'test','status':'running','execution':'independent','instruction':{'revision_text':'動画を制作'}}]))
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True);page=browser.new_page(bypass_csp=True)
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
    page.evaluate("c=>window.__updateEditorContext(c)",{'room_id':room,'content_id':'test','playhead':0,'selected':[]})
    page.evaluate("async()=>{await connect();micOn=true;}")
    started=time.monotonic()
    page.evaluate("()=>{$('input').value='いま進めている動画の制作は中止して。マイクはそのままにして会話は続けたい。';submit();}")
    page.wait_for_function("audit.some(e=>e.type==='tool_finished'&&e.name==='stop_production'&&e.result.ok)",timeout=45000)
    elapsed=round(time.monotonic()-started,2)
    page.wait_for_function("!busy&&!active",timeout=45000)
    assert page.evaluate("micOn&&dc.readyState==='open'")
    assert json.loads((folder/'jobs.json').read_text(encoding='utf-8'))[0]['status']=='failed'
    assert (folder/'jobs/test-job/cancel-requested').exists()
    assert not page.evaluate("audit.some(e=>e.type==='error'||e.type==='response_error')")
    print('STOP_SECONDS',elapsed,'AUDIO_TOKENS',page.evaluate("audit.filter(e=>e.type==='response_done').map(e=>e.usage?.output_token_details?.audio_tokens)"))
    print('REPLY',page.evaluate("audit.filter(e=>e.type==='assistant_transcript').map(e=>e.text)"))
    page.evaluate('disconnect()');browser.close()
