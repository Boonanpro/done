"""Actual GPT-Live WebRTC audio -> client-delegated Astra -> editor presentation."""
import json,time,uuid,os
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

def main():
    editing=os.environ.get('LIVE_TEST_ACTION')=='edit'
    base='http://127.0.0.1:8037';room='live-voice-'+uuid.uuid4().hex[:8]
    folder=Path('uploads/production-assets')/room;folder.mkdir(parents=True)
    (folder/'contents.json').write_text('[]');(folder/'assets.json').write_text('[]')
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    client=httpx.Client(base_url=base,headers={'Authorization':'Bearer '+token},timeout=45)
    cid=client.post('/api/v1/editor-assistant/new',json={'room_id':room}).json()['content_id']
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True,args=['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--use-file-for-fake-audio-capture='+str(Path('scratch/live-test-edit.wav' if editing else 'scratch/live-test-input.wav').resolve())+'%noloop'])
        page=browser.new_page(permissions=['microphone'],viewport={'width':1280,'height':900})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/test-revise.wav',lambda r:r.fulfill(path='scratch/live-test-revise.wav',content_type='audio/wav'))
        page.goto(base+'/api/v1/editor-assistant/page')
        page.evaluate('v=>window.__setEditorAuth(v)',{'token':token})
        page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':cid,'playhead':0,'selected':[]})
        try:
            page.locator('#mic').click()
            page.wait_for_function('()=>liveConnection?.started || $("toast").textContent',timeout=60000)
            assert page.evaluate('liveConnection?.started'),page.locator('#toast').inner_text()
            print('CONNECTED',room,flush=True)
            deadline=time.time()+120
            while time.time()<deadline:
                page.wait_for_timeout(1000)
                v=page.evaluate('()=>({toast:$("toast").textContent,messages:conversationMemory,entries:presentationFeed.size,busy,model:liveConnection?.id})')
                status=client.post('/api/v1/editor-assistant/project-status',json={'room_id':room,'content_id':cid}).json() if editing else {}
                if (status.get('clip_count',0)>0 if editing else v['entries']>0):
                    page.wait_for_timeout(8000)
                    break
                if v['toast']:print('NOTICE',v['toast'],flush=True)
            result=page.evaluate('()=>({messages:conversationMemory,entries:presentationFeed.size,audit:audit.slice(-80),toast:$("toast").textContent})')
            Path('scratch/live-voice-result.json').write_text(json.dumps({'room':room,'content_id':cid,'result':result,'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'room':room,'entries':result['entries'],'messages':result['messages'],'errors':errors},ensure_ascii=False),flush=True)
            if editing:
                from app.services import timeline_live
                content,seq=timeline_live.live_sequence(room,cid)
                page.wait_for_function('()=>!reasonRunning && !busy',timeout=90000)
                page.wait_for_timeout(6000)
                _,seq=timeline_live.live_sequence(room,cid)
                before=json.loads(json.dumps(seq))
                assert status.get('clip_count',0)>0,result['toast']
                page.evaluate("""async()=>{const buffer=await(await fetch('/test-revise.wav')).arrayBuffer();const ac=new AudioContext();window.revisionAudio=ac;const source=ac.createBufferSource();source.buffer=await ac.decodeAudioData(buffer);const out=ac.createMediaStreamDestination();source.connect(out);await pc.getSenders().find(s=>s.track?.kind==='audio').replaceTrack(out.stream.getAudioTracks()[0]);source.start();}""")
                deadline=time.time()+90
                while time.time()<deadline:
                    page.wait_for_timeout(1000)
                    _,seq=timeline_live.live_sequence(room,cid)
                    if any(t in json.dumps(seq,ensure_ascii=False) for t in ['ひと息','ひといき','一息']):break
                assert any(t in json.dumps(seq,ensure_ascii=False) for t in ['ひと息','ひといき','一息']),seq
                Path('scratch/live-edit-proof.json').write_text(json.dumps({'room':room,'content_id':cid,'before':before,'after':seq},ensure_ascii=False,indent=2),encoding='utf-8')
                page.wait_for_function('()=>!reasonRunning && !busy',timeout=60000)
                page.wait_for_timeout(12000)
                after=json.loads(json.dumps(seq))
                for track in after['tracks']:
                    for clip in track['clips']:
                        if 'text' in clip:clip['text']='おかえり'
                assert after==before,(before,after)
                assert any('変更' in x['text'] or '変えた' in x['text'] for x in page.evaluate("conversationMemory.filter(x=>x.role==='assistant')"))
                print('PASS actual voice creation and follow-up text revision',flush=True)
            else:assert result['entries']>0,result['toast']
            assert not errors,errors
        finally:
            page.evaluate("disconnect('test_finished')")
            page.wait_for_timeout(3000)
            page.evaluate('flushAudit()')
            browser.close()

if __name__=='__main__':main()
