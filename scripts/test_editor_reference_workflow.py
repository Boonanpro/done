"""Real conversation -> reference-based production -> preserved format.

Headless browser and an isolated copy; no OS keyboard/window interaction.
"""
import json
import os
import shutil
import time
import uuid
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
from app.services import timeline_draft as td, timeline_live as tl, timeline_scope as scope

source=os.environ.get('EDITOR_REFERENCE_SOURCE','a3970e0b-f7dc-472e-ad63-e8c51382ddb3')
cid='277f96d8-2609-43e9-ba18-bcf3ea37f576'
room='assistant-reference-test-'+uuid.uuid4().hex[:8]
folder=td._room_dir(room);folder.mkdir(parents=True)
content,before=tl.live_sequence(source,cid)
content['room_id']=room
(folder/'contents.json').write_text(json.dumps([content],ensure_ascii=False),encoding='utf-8')
shutil.copy2(td._room_dir(source)/'assets.json',folder/'assets.json')
for f in td._room_dir(source).glob('*_proxy.mp4'):os.link(f,folder/f.name)
token=(Path.home()/'.done/native_token.txt').read_text().strip()
base=os.environ.get('EDITOR_TEST_BASE','http://127.0.0.1:8000/api/v1')
ids=['clip_ag_v_185fc71934','clip_ag_s_6e55992a3d','clip_ag_s_d872e34b34']
with sync_playwright() as p,httpx.Client(headers={'Authorization':'Bearer '+token},timeout=30) as client:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page()
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    page.goto(base+'/editor-assistant/page')
    page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':cid,'playhead':28,'selected':[{'id':i} for i in ids]})
    def say(text):
        page.locator('#input').fill(text);page.locator('#send').click()
        page.wait_for_function('()=>!busy && !active && !retryTimer',timeout=120000)
        page.evaluate('()=>queue')
        page.wait_for_timeout(1500)
        page.wait_for_function('()=>!busy && !active && !retryTimer',timeout=120000)
        print('STATE',page.evaluate('({busy,active,channel:dc?.readyState,state:document.getElementById("state").textContent})'),flush=True)
        print('CONVERSATION',page.locator('#log').inner_text()[-1600:],flush=True)
    say(os.environ.get('EDITOR_REFERENCE_REQUEST') or '選んだ場面の「部品が多い」の画像だけ、前後の年式比較画像と同じ立体的で写実的な見た目に作り直して。元の年式比較画像を参照に使って、単に青いイラストにはしないで。説明と切り替わる位置も元音声を確認して自然に合わせてください。他の場面や字幕、音声、動画の横比率はそのままで。画像生成まで進めてください。')
    deadline=time.monotonic()+900
    last=None
    while time.monotonic()<deadline:
        status=client.post(base+'/editor-assistant/project-status',json={'room_id':room,'content_id':cid}).json()
        jobs=status.get('jobs',[])
        if jobs:
            job=jobs[0]
            stage=(job['status'],(job.get('events') or [{}])[-1].get('text','')[:160])
            if stage!=last:print('PRODUCTION',stage,flush=True);last=stage
            if job['status'] in {'done','failed','canceled'}:break
        elif td.sequence_hash(tl.live_sequence(room,cid)[1]) != td.sequence_hash(before):
            job={'status':'done','kind':'direct_edit'}
            break
        else:raise AssertionError('Conversation did not start production or change the timeline')
        page.wait_for_timeout(3000)
    else:raise AssertionError('Production timed out')
    assert job['status']=='done',job
    after=tl.live_sequence(room,cid)[1]
    for i,entry in scope.clips(before).items():
        if i not in ids:assert scope.clips(after).get(i)==entry,('unrelated change',i)
    saved=td._read_contents_raw(room)[0]
    assert saved['timeline']['format']==saved['timeline']['sequence']['format']=='16:9'
    generated=[a for a in tl._assets(room).values() if a.get('source_type')=='generated']
    assert generated and any(a.get('metadata',{}).get('reference_asset_ids') for a in generated)
    say('何のモデルで作った？今の作業は終わったの？記録を確認して教えて。')
    page.evaluate('flushAudit()')
    (folder/'conversation.txt').write_text(page.locator('#log').inner_text(),encoding='utf-8')
    page.locator('#disconnect').click();browser.close()
print('PASS reference generation, partial edit, format preserved, status available',room,flush=True)
