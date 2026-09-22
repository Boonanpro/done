"""Visible native editor acceptance session. Commands: start, say TEXT, status.

Only the disposable observer project is controlled. Speech goes through the real
Realtime audio input, and is also played locally for the person observing.
"""
import base64,json,os,socket,subprocess,sys,time,uuid,wave
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'uploads/editor-observer.json'

def start():
    room='observer-'+uuid.uuid4().hex[:8]
    folder=ROOT/'uploads/production-assets'/room;folder.mkdir(parents=True)
    cid=uuid.uuid4().hex
    (folder/'contents.json').write_text(json.dumps([{'id':cid,'title':'見学テスト：説明が苦手なユーザーとの制作','room_id':room,'created_at':'2026-09-07T00:00:00Z','updated_at':'2026-09-07T00:00:00Z','timeline':{'format':'16:9','sequence':{'duration':0,'format':'16:9','tracks':[]}}}],ensure_ascii=False),encoding='utf-8')
    (folder/'assets.json').write_text('[]',encoding='utf-8')
    silence=folder/'silence.wav'
    with wave.open(str(silence),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(b'\0\0'*48000*90)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={**os.environ,'DONE_EDITOR_VOICE':'1','WEBVIEW2_USER_DATA_FOLDER':str(folder/'webview'),
         'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS':f'--remote-debugging-port={port} --use-fake-ui-for-media-stream --use-fake-device-for-media-stream --use-file-for-fake-audio-capture={silence}'}
    exe=ROOT/'scripts/poc/production_desktop/native_ui/target/release/native_ui.exe'
    proc=subprocess.Popen([str(exe),str(folder/'contents.json'),str(folder)],env=env,stdout=subprocess.DEVNULL,stderr=(folder/'native.log').open('w'))
    value={'room':room,'content_id':cid,'folder':str(folder),'port':port,'pid':proc.pid}
    STATE.write_text(json.dumps(value),encoding='utf-8');print(json.dumps(value),flush=True)

def run(command):
    cfg=json.loads(STATE.read_text(encoding='utf-8'));folder=Path(cfg['folder'])
    audio=None
    if command=='say':
        text=' '.join(sys.argv[2:]);assert text
        textfile=folder/'utterance.txt';textfile.write_text(text,encoding='utf-8')
        wav=folder/'utterance.wav'
        code=f"Add-Type -AssemblyName System.Speech; $voice=New-Object System.Speech.Synthesis.SpeechSynthesizer; $voice.SelectVoice('Microsoft Haruka Desktop'); $voice.SetOutputToWaveFile('{wav}'); $voice.Speak([IO.File]::ReadAllText('{textfile}',[Text.Encoding]::UTF8)); $voice.Dispose()"
        subprocess.run(['powershell','-NoProfile','-EncodedCommand',base64.b64encode(code.encode('utf-16le')).decode()],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        audio=base64.b64encode(wav.read_bytes()).decode()
    with sync_playwright() as p:
        browser=p.chromium.connect_over_cdp(f"http://127.0.0.1:{cfg['port']}")
        page=next(x for c in browser.contexts for x in c.pages if 'editor-assistant/page' in x.url)
        page.evaluate('''()=>{
          if(!window.observerEvents){window.observerEvents=[];const original=record;record=(type,data={})=>{observerEvents.push({at:new Date().toISOString(),type,...data});original(type,data);};}
          if(!window.observerTranscriptions){window.observerTranscriptions=[];const originalEvent=onEvent;onEvent=e=>{if(e.type.includes('input_audio_transcription'))observerTranscriptions.push(e);return originalEvent(e);};}
        }''')
        if command=='pause':
            page.evaluate("disconnect('observer_paused')")
            print('Observer voice paused; window retained',flush=True)
        elif command=='reload':
            captured=page.evaluate('context')
            page.evaluate("disconnect('observer_update')")
            page.reload()
            page.evaluate('(c)=>window.__updateEditorContext(c)',captured)
            for _ in range(60):
                if page.evaluate("micOn && dc?.readyState === 'open'"):break
                time.sleep(0.5)
            else:raise RuntimeError('Observer voice did not reconnect')
            print('Reloaded observer UI; voice reconnected',flush=True)
        elif command=='say':
            result=page.evaluate('''async b64=>{
              if(!micOn||dc?.readyState!=='open')throw Error('The observer microphone is not connected');
              if(!window.observerAudio){
                window.observerAudio=new AudioContext();window.observerCapture=observerAudio.createMediaStreamDestination();
              }
              await observerAudio.resume();
              if(!window.observerSilence){
                // Keep sending silent samples after the utterance ends, like a
                // live microphone. A disconnected graph can starve server VAD.
                window.observerSilence=observerAudio.createBufferSource();
                observerSilence.buffer=observerAudio.createBuffer(1,48000,48000);
                observerSilence.loop=true;observerSilence.connect(observerCapture);observerSilence.start();
              }
              const bytes=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));
              const buffer=await observerAudio.decodeAudioData(bytes.buffer);
              const sender=pc.getSenders().find(s=>s.track?.kind==='audio');
              await sender.replaceTrack(observerCapture.stream.getAudioTracks()[0]);
              const source=observerAudio.createBufferSource();source.buffer=buffer;
              source.connect(observerCapture);source.connect(observerAudio.destination);
              window.observerSpeaking=true;source.onended=()=>{observerSpeaking=false;source.disconnect();record('observer_audio_finished');};
              record('observer_audio_started',{seconds:buffer.duration});source.start();return {seconds:buffer.duration};
            }''',audio)
            print(json.dumps(result),flush=True)
        elif command=='screenshot':
            page.screenshot(path=str(folder/'stage.png'));print(str(folder/'stage.png'))
        elif command=='play':
            index=int(sys.argv[2]) if len(sys.argv)>2 else 0
            element=page.locator('#reference-cards iframe').nth(index)
            box=element.bounding_box()
            page.mouse.click(box['x']+box['width']/2,box['y']+box['height']/2)
            print('Playing reference in the editor',index,flush=True)
        elif command=='preview':
            page.evaluate("nativeCommand('stage_compact');nativeCommand('toggle_play')")
            print('Playing timeline in the visible editor',flush=True)
        else:
            data=page.evaluate('''()=>({micOn,busy,active,audioPlaying,context,state:document.getElementById('state').textContent,toast:document.getElementById('toast').textContent,events:observerEvents.slice(-40),transcriptions:observerTranscriptions.slice(-40),references:[...document.querySelectorAll('#reference-cards a')].map(x=>({text:x.textContent,url:x.href}))})''')
            (folder/'observer-status.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(data,ensure_ascii=False),flush=True)

if __name__=='__main__':
    if sys.argv[1]=='start':start()
    else:run(sys.argv[1])
