"""A multi-turn real Realtime session editing a copy of the user's project."""
import copy
import os
import json
import shutil
import time
import uuid
from pathlib import Path
from playwright.sync_api import sync_playwright
from app.services import timeline_draft as td,timeline_live as tl,timeline_scope as scope

source='a3970e0b-f7dc-472e-ad63-e8c51382ddb3';cid='277f96d8-2609-43e9-ba18-bcf3ea37f576'
room='assistant-conversation-test-'+uuid.uuid4().hex[:8]
folder=td._room_dir(room);folder.mkdir(parents=True)
content,before=tl.live_sequence(source,cid)
(folder/'contents.json').write_text(json.dumps([content],ensure_ascii=False),encoding='utf-8')
shutil.copy2(td._room_dir(source)/'assets.json',folder/'assets.json')
shutil.copytree(td._room_dir(source)/'assistant/audio-analysis',folder/'assistant/audio-analysis')
token=os.environ.get('EDITOR_TEST_TOKEN') or (Path.home()/'.done/native_token.txt').read_text().strip()
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page()
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
    def context(ids):
        page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':cid,'playhead':132.5,'selected':[{'id':i} for i in ids]})
    def say(text):
        page.locator('#input').fill(text);page.locator('#send').click()
        page.wait_for_function('()=>!busy && !active && !retryTimer',timeout=120000)
        print('TURN',text,'\n',page.locator('#log').inner_text()[-1200:],flush=True)
    ids=['clip_ag_c_bf4202c7f5','clip_ag_c_f295fb9ee9'];context(ids)
    say('選んだ二つの字幕の境界を元音声の「弊社」の始まりに合わせて。文言は今のままで。')
    _,seq=tl.live_sequence(room,cid)
    assert abs(scope.clips(seq)[ids[1]][1]['timeline_start']-132.93)<.04
    context([]);page.select_option('#scope','whole')
    say('動画全体に、手元の音楽素材からBGMを付けて。話し声を邪魔しない音量にして。')
    _,seq=tl.live_sequence(room,cid)
    music=[c for t in seq['tracks'] for c in t['clips'] if c.get('role')=='music']
    assert music, 'BGM was not placed'
    mid=music[0]['id'];volume=music[0]['volume'];context([mid]);page.select_option('#scope','selected')
    say('選択したBGMの音量を今の半分にして。それ以外は変えないで。')
    _,seq=tl.live_sequence(room,cid)
    assert abs(scope.clips(seq)[mid][1]['volume']-volume/2)<.001
    say('ここまでに変更したことだけ、短く教えて。')
    page.evaluate('flushAudit()');page.wait_for_timeout(500)
    usage=[]
    for f in (folder/'assistant/events').glob('*.jsonl'):
        for line in f.read_text(encoding='utf-8').splitlines():
            row=json.loads(line)
            if row['type']=='response_done' and row.get('usage'):usage.append(row['usage'].get('input_tokens',0))
    print('input_tokens_per_response',usage,'room',room,flush=True)
    assert usage and max(usage)<20000
    assert 'Rate limit reached' not in page.locator('#log').inner_text()
    page.locator('#disconnect').click();browser.close()
