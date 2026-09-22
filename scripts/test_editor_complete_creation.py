"""Consultation -> complete editable draft -> scoped edit -> actual export.

Uses the same conversation UI in headless Chromium, isolated room and server.
The topic is a declared test fixture, not a user's approved creative brief.
"""
import json
import os
import time
import uuid
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright
from app.services import timeline_draft as td, timeline_live as tl, timeline_scope as scope

base=os.environ.get('EDITOR_TEST_BASE','http://127.0.0.1:8011/api/v1')
resume=os.environ.get('EDITOR_RESUME_ROOM')
room=resume or 'assistant-complete-test-'+uuid.uuid4().hex[:8]
folder=td._room_dir(room);folder.mkdir(parents=True,exist_ok=bool(resume))
if not resume:
    (folder/'contents.json').write_text('[]',encoding='utf-8')
    (folder/'assets.json').write_text('[]',encoding='utf-8')
token=(Path.home()/'.done/native_token.txt').read_text().strip()

with httpx.Client(headers={'Authorization':'Bearer '+token},timeout=60) as client,sync_playwright() as p:
    def post(path,body):
        r=client.post(base+'/editor-assistant/'+path,json=body);r.raise_for_status();return r.json()
    cid=td._read_contents_raw(room)[0]['id'] if resume else post('new',{'room_id':room})['content_id']
    print('PROJECT',room,cid,flush=True)
    browser=p.chromium.launch(headless=True)
    page=browser.new_page()
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    page.goto(base+'/editor-assistant/page')
    ctx={'room_id':room,'content_id':cid,'playhead':0,'selected':[],'scope_mode':'whole'}
    page.evaluate('c=>window.__updateEditorContext(c)',ctx)
    page.locator('#scope').select_option('whole')
    def say(text):
        page.locator('#input').fill(text);page.locator('#send').click()
        page.wait_for_function('()=>!busy && !active && !retryTimer',timeout=180000)
        page.evaluate('()=>queue');page.wait_for_timeout(1500)
        page.wait_for_function('()=>!busy && !active && !retryTimer',timeout=180000)
        conversation=page.locator('#log').inner_text()
        (folder/('resume-conversation.txt' if resume else 'conversation.txt')).write_text(conversation,encoding='utf-8')
        print('CONVERSATION',conversation[-1800:],flush=True)
    def wait_job(previous):
        deadline=time.monotonic()+1500;last=None
        while time.monotonic()<deadline:
            status=post('project-status',{'room_id':room,'content_id':cid})
            jobs=[j for j in status['jobs'] if j['id'] not in previous]
            if jobs:
                job=jobs[0];stage=(job['status'],(job.get('events') or [{}])[-1].get('text','')[:180])
                if stage!=last:print('JOB',stage,flush=True);last=stage
                if job['status'] in {'done','failed','canceled'}:
                    assert job['status']=='done',job
                    return job
            page.wait_for_timeout(3000)
        raise AssertionError('Production did not finish within test deadline')
    if not resume:
        say('吉川とは別のテスト作品です。架空の小さな珈琲店の、朝に見たら寄りたくなる15秒くらいの横動画を作りたい。忙しい社会人向けで、柔らかい朝の光と静かな映画みたいな雰囲気。素材はありません。声と映像と字幕のある下書きが欲しいです。まず短く作り方とテイストを提案して。')
        say('その方向で作ってください。ナレーションは登録済みの本人の声で。店名や実在店の情報は不要です。全体の尺は自然な声に合わせて多少前後して大丈夫。まず安い形の通しの下書きで、絵も字幕も声も編集できる状態にしてください。')
    job=wait_job(set())
    saved,seq=tl.live_sequence(room,cid)
    assert saved.get('creative_brief'), 'Brief was not remembered'
    assert saved['timeline']['format']==seq['format']=='16:9'
    clips=scope.clips(seq)
    visuals=[c for _,c in clips.values() if c.get('asset_id') and tl._assets(room).get(c['asset_id'],{}).get('kind') in {'image','video'}]
    sounds=[c for _,c in clips.values() if c.get('asset_id') and tl._assets(room).get(c['asset_id'],{}).get('kind')=='audio']
    captions=[c for _,c in clips.values() if c.get('text')]
    assert visuals and sounds and captions,(len(visuals),len(sounds),len(captions))
    assert seq['duration']>=10
    print('FULL_DRAFT',len(visuals),len(sounds),len(captions),seq['duration'],flush=True)
    selected=captions[0]
    ctx.update(playhead=selected['timeline_start']+.1,selected=[{'id':selected['id']}],scope_mode='selected')
    page.evaluate('c=>window.__updateEditorContext(c)',ctx)
    page.locator('#scope').select_option('selected')
    say('選んだ字幕だけ少し小さくして。文字の内容も他の場面もそのまま。')
    _,after=tl.live_sequence(room,cid)
    assert scope.clips(after)[selected['id']]!=clips[selected['id']],'Requested edit did not happen'
    for key,value in clips.items():
        if key!=selected['id']:assert scope.clips(after).get(key)==value,('Unrelated change',key)
    before_jobs={j['id'] for j in post('project-status',{'room_id':room,'content_id':cid})['jobs']}
    say('今の動画を動画ファイルに書き出して。')
    exported=wait_job(before_jobs)
    (folder/'acceptance.json').write_text(json.dumps({'room':room,'content_id':cid,'draft_job':job,'export':exported},ensure_ascii=False,indent=2),encoding='utf-8')
    page.locator('#disconnect').click();browser.close()
print('PASS consultation, complete draft, partial edit, export',room,cid,flush=True)
