"""Actual mixed-input voice session edits a video property without generation."""
import copy,json,time,uuid
from pathlib import Path
from playwright.sync_api import sync_playwright
from app.services import timeline_draft as td

source=td._room_dir('collage-acceptance-2db12005')
room='video-fast-edit-'+uuid.uuid4().hex[:8];folder=td._room_dir(room);folder.mkdir(parents=True)
content=json.loads((source/'contents.json').read_text(encoding='utf-8'))[0]
before=copy.deepcopy(content['timeline']['sequence'])
target=next(c for t in before['tracks'] for c in t['clips'] if c['id']=='clip_ag_s_d6bbe2f301')
(folder/'contents.json').write_text(json.dumps([content],ensure_ascii=False),encoding='utf-8')
(folder/'assets.json').write_bytes((source/'assets.json').read_bytes())
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True);page=browser.new_page(bypass_csp=True)
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
    page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':content['id'],'playhead':3,'selected':[target]})
    page.evaluate('async()=>{await connect();micOn=true;}')
    started=time.monotonic()
    page.evaluate("()=>{$('input').value='選択した映像の不透明度を50%にして。字幕やほかの映像は触らないで。';submit();}")
    page.wait_for_function("audit.some(e=>e.type==='tool_finished'&&e.result?.committed)",timeout=45000)
    elapsed=round(time.monotonic()-started,2)
    after=json.loads((folder/'contents.json').read_text(encoding='utf-8'))[0]['timeline']['sequence']
    old={c['id']:c for t in before['tracks'] for c in t['clips']};new={c['id']:c for t in after['tracks'] for c in t['clips']}
    assert new[target['id']]['opacity']==.5
    assert all(new[i]==c for i,c in old.items() if i!=target['id'])
    assert not page.evaluate("audit.some(e=>e.type==='tool_started'&&e.name==='delegate_edit')")
    print('PASS video opacity, other clips preserved, no generation/delegation; request-to-save seconds',elapsed)
    page.evaluate('disconnect()');browser.close()
