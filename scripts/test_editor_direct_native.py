"""Real native editor + conversation API. No synthetic editor-state claims."""
import json,os,socket,subprocess,time,uuid,wave,base64,ctypes
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
from app.services.auth_service import create_access_token
from app.services import timeline_draft as td

BASE=os.environ.get('EDITOR_TEST_BASE','http://127.0.0.1:8029')
ROOT=Path(__file__).resolve().parents[1]

def main():
    room='direct-native-'+uuid.uuid4().hex[:8];folder=td._room_dir(room);folder.mkdir(parents=True)
    (folder/'contents.json').write_text('[]');(folder/'assets.json').write_text('[]')
    token=create_access_token('2582a188-ff24-4a4f-b989-6063034d90b2','bold1315@icloud.com')
    with httpx.Client(base_url=BASE,headers={'Authorization':'Bearer '+token},timeout=60) as client:
        response=client.post('/api/v1/editor-assistant/new',json={'room_id':room});response.raise_for_status();cid=response.json()['content_id']
    with wave.open(str(folder/'silence.wav'),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(bytes(32000*120))
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={**os.environ,'DONE_EDITOR_VOICE':'1','WEBVIEW2_USER_DATA_FOLDER':str(folder/'webview'),
         'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS':f'--remote-debugging-port={port} --use-fake-ui-for-media-stream --use-fake-device-for-media-stream --use-file-for-fake-audio-capture='+str(folder/'silence.wav')}
    proc=subprocess.Popen([os.environ.get('EDITOR_TEST_EXE',str(ROOT/'scripts/poc/production_desktop/native_ui/target/release/native_ui.exe')),str(folder/'contents.json'),str(folder)],env=env,stdout=subprocess.DEVNULL,stderr=(folder/'native.log').open('w'))
    report={'room':room,'content_id':cid,'pid':proc.pid,'steps':[]}
    try:
        with sync_playwright() as p:
            browser=None
            for _ in range(100):
                try:browser=p.chromium.connect_over_cdp(f'http://127.0.0.1:{port}');break
                except Exception:time.sleep(.2)
            assert browser,'Native WebView unavailable'
            page=None
            for _ in range(100):
                if browser.contexts:browser.contexts[0].cookies()
                page=next((x for c in browser.contexts for x in c.pages if 'editor-assistant/page' in x.url),None)
                if page:break
                time.sleep(.2)
            assert page,[(x.url) for c in browser.contexts for x in c.pages]
            page.context.new_cdp_session(page).send('Page.setBypassCSP',{'enabled':True})
            page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
            if BASE!='http://127.0.0.1:8000':
                page.route('http://127.0.0.1:8000/**',lambda route:route.fulfill(response=route.fetch(url=route.request.url.replace('http://127.0.0.1:8000',BASE))))
            page.reload()
            page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':cid,'playhead':0,'selected':[]})
            page.evaluate("async()=>{$('scope').value='whole';await connect();micOn=true;mic?.getTracks().forEach(t=>t.enabled=false);nativeCommand('stage_compact');}")
            page.wait_for_function('context?.content_id',timeout=15000)
            def seq():return td._content_sequence(td._read_contents_raw(room)[0])
            def run(text,check,voice=False):
                if voice:
                    spoken=folder/'spoken.txt';spoken.write_text(text,encoding='utf-8');wav=folder/'spoken.wav'
                    script=f"Add-Type -AssemblyName System.Speech; $synth=New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.SelectVoice('Microsoft Haruka Desktop'); $synth.SetOutputToWaveFile('{wav}'); $synth.Speak([IO.File]::ReadAllText('{spoken}',[Text.Encoding]::UTF8)); $synth.Dispose()"
                    subprocess.run(['powershell','-NoProfile','-EncodedCommand',base64.b64encode(script.encode('utf-16le')).decode()],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
                began=time.monotonic()
                if voice:
                    page.evaluate("""async b64=>{
                        const ac=new AudioContext();await ac.resume();window.testAudio=ac;
                        const capture=ac.createMediaStreamDestination();
                        const silent=ac.createBufferSource();silent.buffer=ac.createBuffer(1,48000,48000);silent.loop=true;silent.connect(capture);silent.start();
                        await pc.getSenders().find(s=>s.track?.kind==='audio').replaceTrack(capture.stream.getAudioTracks()[0]);
                        const buffer=await ac.decodeAudioData(Uint8Array.from(atob(b64),c=>c.charCodeAt(0)).buffer);
                        const source=ac.createBufferSource();source.buffer=buffer;source.connect(capture);source.connect(ac.destination);source.start();
                        window.testVoiceSeconds=buffer.duration;
                    }""",base64.b64encode(wav.read_bytes()).decode())
                else:page.evaluate("text=>{$('input').value=text;submit();}",text)
                until=time.monotonic()+120
                while time.monotonic()<until:
                    if check(seq()):break
                    page.wait_for_timeout(100)
                else:raise AssertionError('Requested edit not saved: '+text)
                saved=round(time.monotonic()-began,2)
                page.wait_for_function('!reasonRunning&&!busy&&!relayActive&&!audioPlaying&&relayQueue.length===0',timeout=120000)
                report['steps'].append({'request':text,'input':'voice' if voice else 'text','saved_seconds':saved,'speech_seconds':page.evaluate('window.testVoiceSeconds||0') if voice else 0,'response_seconds':round(time.monotonic()-began,2)})
                print('STEP',report['steps'][-1],flush=True)
                page.wait_for_timeout(1200)
                state=json.loads((folder/'editor_state.json').read_text(encoding='utf-8'))
                assert state.get('content_id')==cid,state
                assert state.get('pixels_per_second',0)>100,state
                report['steps'][-1]['pixels_per_second']=state['pixels_per_second']
            if os.environ.get('EDITOR_TEST_FOCUS')=='voice-add':
                from app.services.editor_media import import_media
                from app.services.editor_workflows import batch_edit
                asset=import_media(room,str(ROOT/'exports/omni-direct-comparison/b_from_reference.mp4'))
                assert asset['ok'];duration=asset['metadata']['duration']
                result=batch_edit(room,cid,[{'op':'add_clip','args':{'asset_id':asset['asset_id'],'timeline_start':0,'duration':duration,'with_audio':True}},
                    {'op':'add_caption','args':{'text':'これが完成形','timeline_start':duration-1,'timeline_end':duration,'lane':'front'}}],None,td.sequence_hash(seq()))
                assert result['committed'];page.wait_for_timeout(1800)
                page.evaluate("$('scope').value='selected'")
                baseline=seq()
                run('最後の半秒に、右上へ「またね」も加えて。',lambda s:any(c.get('text')=='またね' for t in s['tracks'] for c in t['clips']),voice=True)
                old_ids={c['id'] for t in baseline['tracks'] for c in t['clips']}
                assert [c for t in baseline['tracks'] for c in t['clips']]==[c for t in seq()['tracks'] for c in t['clips'] if c['id'] in old_ids]
                run('今追加した「またね」だけを消して。',lambda s:not any(c.get('text')=='またね' for t in s['tracks'] for c in t['clips']),voice=True)
                assert [c for t in baseline['tracks'] for c in t['clips']]==[c for t in seq()['tracks'] for c in t['clips']]
            else:
                run('既存のBを元音声付きでここに全尺配置して。ファイルは D:/done/exports/omni-direct-comparison/b_from_reference.mp4 。新規生成は不要です。',lambda s:any(t.get('type')=='audio' and t.get('clips') for t in s['tracks']))
                run('最後の1秒に「確認用B」と白い文字を載せて。',lambda s:any(c.get('text')=='確認用B' for t in s['tracks'] for c in t['clips']))
                before=seq()
                run('今足した文字だけ「これが完成形」に変えて。映像と音声はそのまま。',lambda s:any(c.get('text')=='これが完成形' for t in s['tracks'] for c in t['clips']))
                after=seq()
                assert [c for t in before['tracks'] for c in t['clips'] if c.get('asset_id')]==[c for t in after['tracks'] for c in t['clips'] if c.get('asset_id')]
                caption=next(c for t in after['tracks'] for c in t['clips'] if c.get('text')=='これが完成形')
                size=caption.get('style',{}).get('fontSize',1)
                run('さっきの最後の文字を、もう少し大きくして。',lambda s:any(c.get('id')==caption['id'] and c.get('style',{}).get('fontSize',1)>size for t in s['tracks'] for c in t['clips']),voice=True)
                run('映像や文字はそのままで、動画の音量だけ半分にして。',lambda s:all(abs(c.get('volume',1)-0.5)<0.01 for t in s['tracks'] if t['type']=='audio' for c in t['clips']),voice=True)
                run('映像を二秒のところで分割して。音声も一緒に切って、再生の順番や長さは変えないで。',lambda s:len([c for t in s['tracks'] if t['type']=='video' for c in t['clips'] if c.get('asset_id')])==2 and len([c for t in s['tracks'] if t['type']=='audio' for c in t['clips']])==2,voice=True)
                assert abs(seq()['duration']-before['duration'])<0.001
                for kind in ('audio','video'):
                    pieces=sorted([c for t in seq()['tracks'] if t['type']==kind for c in t['clips'] if c.get('asset_id')],key=lambda c:c['timeline_start'])
                    assert [(c['timeline_start'],c['timeline_end']) for c in pieces]==[(0,2),(2,before['duration'])]
                    assert [(c['source_start'],c['source_end']) for c in pieces]==[(0,2),(2,before['duration'])]
                assert seq().get('format')=='16:9'
            page.evaluate('async()=>{await editorAction({kind:"seek",content_id:context.content_id,t:4.5});}')
            page.wait_for_timeout(1200)
            from scripts.poc.production_desktop.native_ui.selftest_gpu_present import shot
            @ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
            def capture(hwnd,_):
                pid=ctypes.c_ulong();ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                if pid.value==proc.pid and ctypes.windll.user32.IsWindowVisible(hwnd):
                    rect=ctypes.wintypes.RECT();ctypes.windll.user32.GetWindowRect(hwnd,ctypes.byref(rect))
                    if rect.right-rect.left>500 and rect.bottom-rect.top>400:shot(hwnd,str(folder/'native.png'))
                return True
            ctypes.windll.user32.EnumWindows(capture,0)
            page.evaluate('async()=>{await editorAction({kind:"seek",content_id:context.content_id,t:0});}')
            # Actual native playback command: observe playhead progression on disk.
            page.evaluate("nativeCommand('toggle_play')")
            page.wait_for_timeout(900);first=json.loads((folder/'editor_state.json').read_text(encoding='utf-8'))
            deadline=time.monotonic()+4
            second=first
            while time.monotonic()<deadline:
                page.wait_for_timeout(150);second=json.loads((folder/'editor_state.json').read_text(encoding='utf-8'))
                if second.get('playhead',0)>first.get('playhead',0)+0.2:break
            report['playback']={'first':first,'second':second}
            assert second.get('playhead',0)>first.get('playhead',0)+0.2,report['playback']
            page.evaluate("nativeCommand('toggle_play')")
            report['ui']=page.evaluate('({memory:conversationMemory,audit,jobs:[...jobs],messages:[...$("log").querySelectorAll(".message")].map(e=>({kind:e.className,text:e.textContent}))})')
            assert not report['ui']['jobs'],'Simple edits unexpectedly delegated'
            assert not [m for m in report['ui']['messages'] if 'error' in m['kind']],report['ui']['messages']
            page.evaluate('flushAudit()');page.screenshot(path=str(folder/'assistant.png'))
            page.evaluate("disconnect('test_finished')")
            page.unroute_all(behavior='wait')
            print('PASS',room,flush=True)
    finally:
        (folder/'direct-native-e2e.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        # Only this disposable test window is closed.
        proc.terminate();proc.wait(timeout=15)
if __name__=='__main__':main()
