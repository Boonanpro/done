"""Actual browser, GPT6, Realtime speech, and isolated timeline edits."""
import json,time,uuid
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
from app.services.auth_service import create_access_token
from app.services import timeline_draft as td

BASE='http://127.0.0.1:8029'
def main():
    room='reasoning-e2e-'+uuid.uuid4().hex[:8]
    folder=td._room_dir(room);folder.mkdir(parents=True)
    (folder/'contents.json').write_text('[]');(folder/'assets.json').write_text('[]')
    token=create_access_token('2582a188-ff24-4a4f-b989-6063034d90b2','bold1315@icloud.com')
    with httpx.Client(base_url=BASE,headers={'Authorization':'Bearer '+token},timeout=60) as client:
        r=client.post('/api/v1/editor-assistant/new',json={'room_id':room});r.raise_for_status();cid=r.json()['content_id']
    report={'room':room,'content_id':cid,'turns':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--autoplay-policy=no-user-gesture-required'])
        page=browser.new_page(bypass_csp=True)
        page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
        page.goto(BASE+'/api/v1/editor-assistant/page')
        page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':cid,'playhead':0,'selected':[]})
        page.evaluate('async()=>{await connect();micOn=true;}')
        def say(text):
            start=time.monotonic();page.evaluate("text=>{$('input').value=text;submit();}",text)
            page.wait_for_function('!busy&&!reasonRunning&&!relayActive&&!audioPlaying&&relayQueue.length===0',timeout=120000)
            result=page.evaluate('({messages:[...$("log").querySelectorAll(".message")].map(e=>({kind:e.className,text:e.textContent})),audit:[...audit],memory:[...conversationMemory],turn})')
            row={'text':text,'seconds':round(time.monotonic()-start,2),'state':result};report['turns'].append(row)
            print(text,'seconds',row['seconds'],'last',result['messages'][-1],flush=True)
            errors=[m for m in result['messages'] if 'error' in m['kind']]
            assert not errors,errors
            return result
        say('仕事帰りの一人客が、気兼ねなく入れる焼き鳥屋の動画を作りたい。今は覚えておくだけで、検索も制作もしないで。')
        r=say('今どんな人向けに作りたいと言ったっけ？')
        assert '仕事帰り' in r['messages'][-1]['text']
        say('テストで字幕を一つ置いて。0秒から3秒まで「仕事帰りに、ひと串。」。素材や動画の生成はしないで。')
        seq=td._content_sequence(td._read_contents_raw(room)[0]);clips=[c for t in seq['tracks'] for c in t['clips']]
        assert any(c.get('text')=='仕事帰りに、ひと串。' for c in clips),clips
        target=next(c for c in clips if c.get('text'))
        page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':cid,'playhead':1,'selected':[{'id':target['id']}]})
        say('その字幕の文言だけ「今日は、ひとりで。」に変えて。時間は変えないで。')
        seq=td._content_sequence(td._read_contents_raw(room)[0]);after=next(c for t in seq['tracks'] for c in t['clips'] if c['id']==target['id'])
        assert after['text']=='今日は、ひとりで。'
        assert (after['timeline_start'],after['timeline_end'])==(target['timeline_start'],target['timeline_end'])
        page.evaluate('async()=>{await flushAudit();disconnect();}')
        browser.close()
    (folder/'reasoning-e2e.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS',room,cid,flush=True)
if __name__=='__main__':main()
