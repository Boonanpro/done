"""Real microphone transport and broad editing on the completed new-topic draft."""
import json,time,wave
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
from app.services import timeline_speech as speech,timeline_live as tl,timeline_draft as td

room='assistant-complete-test-8e96bdba';cid='a65ccfdd-6304-4dee-9fa4-c06d79ab921c'
folder=td._room_dir(room)
command='全体をもう少しゆったりした感じにして。ナレーションが少し早口なので、自然な範囲でゆっくりにして間を取って。後半の映像に出ている黒い余白をなくして。最後の字幕も他と同じ雰囲気に揃えて。素材の作り直しはしなくていいです。'
wav=folder/'voice-refinement-command.wav'
if not wav.exists():
    result=speech.synthesize(command,wav)
    assert result['ok'],result
capture=folder/'voice-refinement-capture.wav'
with wave.open(str(wav),'rb') as src,wave.open(str(capture),'wb') as dest:
    dest.setparams(src.getparams())
    dest.writeframes(b'\0'*(src.getframerate()*src.getnchannels()*src.getsampwidth()*2))
    dest.writeframes(src.readframes(src.getnframes()))
    dest.writeframes(b'\0'*(src.getframerate()*src.getnchannels()*src.getsampwidth()*20))
token=(Path.home()/'.done/native_token.txt').read_text().strip()
base='http://127.0.0.1:8011/api/v1'
before=td.sequence_hash(tl.live_sequence(room,cid)[1])
with sync_playwright() as p,httpx.Client(headers={'Authorization':'Bearer '+token},timeout=60) as client:
    def status():
        r=client.post(base+'/editor-assistant/project-status',json={'room_id':room,'content_id':cid});r.raise_for_status();return r.json()
    old={j['id'] for j in status()['jobs']}
    browser=p.chromium.launch(headless=True,args=['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--use-file-for-fake-audio-capture='+str(capture.resolve())])
    page=browser.new_page(viewport={'width':360,'height':760})
    errors=[]
    page.on('pageerror',lambda e: errors.append(str(e)))
    page.on('requestfailed',lambda r: errors.append(r.url.split('?')[0]+': '+str(r.failure)))
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    page.goto(base+'/editor-assistant/page')
    page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':cid,'playhead':8,'selected':[]})
    page.locator('#scope').select_option('whole')
    page.locator('#mic').click()
    deadline=time.monotonic()+180;heard=False
    while time.monotonic()<deadline:
        page.wait_for_timeout(500)
        if page.locator('#log .user').count():
            heard=True;page.locator('#mic').click();break
    if not heard:
        print('DIAGNOSTICS',page.evaluate('()=>({state:$("state").textContent,log:$("log").innerText,micOn,connecting:!!connecting,channel:dc?.readyState,connection:pc?.connectionState,ice:pc?.iceConnectionState,tracks:mic?.getTracks().map(t=>({enabled:t.enabled,state:t.readyState,muted:t.muted}))})'),errors,flush=True)
        page.evaluate('flushAudit()')
        page.screenshot(path=str(folder/'voice-refinement-failure.png'))
    assert heard,'No microphone transcript'
    page.wait_for_function('()=>!busy && !active && !retryTimer',timeout=180000)
    page.evaluate('()=>queue');page.wait_for_timeout(1500)
    print('CONVERSATION',page.locator('#log').inner_text(),flush=True)
    deadline=time.monotonic()+1200;last=None
    while time.monotonic()<deadline:
        new=[j for j in status()['jobs'] if j['id'] not in old]
        if new:
            job=new[0];stage=(job['status'],(job.get('events') or [{}])[-1].get('text','')[:170])
            if stage!=last:print('JOB',stage,flush=True);last=stage
            if job['status'] in {'done','failed','canceled'}:
                assert job['status']=='done',job;break
        elif td.sequence_hash(tl.live_sequence(room,cid)[1])!=before:break
        page.wait_for_timeout(3000)
    else:raise AssertionError('Voice request was not executed')
    (folder/'voice-refinement-conversation.txt').write_text(page.locator('#log').inner_text(),encoding='utf-8')
    page.evaluate('flushAudit()');page.screenshot(path=str(folder/'voice-refinement-panel.png'))
    page.locator('#disconnect').click();browser.close()
assert td.sequence_hash(tl.live_sequence(room,cid)[1])!=before
print('PASS voice led to non-caption video refinement',room,flush=True)
