"""Drive a disposable native editor through its actual conversation UI.

The observer writes command.json with {id, text, voice?}; result.json records
the response. No production tools or model responses are simulated.
"""
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import uuid
import wave

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    room='observed-trial-'+uuid.uuid4().hex[:8]
    folder=ROOT/'uploads/production-assets'/room
    folder.mkdir(parents=True)
    (folder/'contents.json').write_text('[]')
    (folder/'assets.json').write_text('[]')
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    with httpx.Client(headers={'Authorization':'Bearer '+token},timeout=30) as client:
        r=client.post('http://127.0.0.1:8000/api/v1/editor-assistant/new',json={'room_id':room})
        r.raise_for_status();cid=r.json()['content_id']
    with wave.open(str(folder/'silence.wav'),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(bytes(32000*120))
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    env={**os.environ,'DONE_EDITOR_VOICE':'1','WEBVIEW2_USER_DATA_FOLDER':str(folder/'webview'),
         'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS':f'--remote-debugging-port={port} --use-fake-ui-for-media-stream --use-fake-device-for-media-stream --use-file-for-fake-audio-capture='+str(folder/'silence.wav')}
    proc=subprocess.Popen([str(ROOT/'scripts/poc/production_desktop/native_ui/target/release/native_ui.exe'),str(folder/'contents.json'),str(folder)],
                          env=env,stdout=subprocess.DEVNULL,stderr=(folder/'native.log').open('w'))
    info={'room_id':room,'content_id':cid,'pid':proc.pid,'cdp_port':port}
    (ROOT/'scratch/observed-trial-current.json').write_text(json.dumps(info))
    print(json.dumps(info),flush=True)
    try:
        with sync_playwright() as pw:
            browser=None
            for _ in range(100):
                try:browser=pw.chromium.connect_over_cdp(f'http://127.0.0.1:{port}');break
                except Exception:time.sleep(.2)
            if browser is None:raise RuntimeError('Native WebView unavailable')
            page=None
            for _ in range(100):
                if browser.contexts:browser.contexts[0].cookies()
                page=next((p for c in browser.contexts for p in c.pages if 'editor-assistant/page' in p.url),None)
                if page:break
                time.sleep(.2)
            if page is None:raise RuntimeError('Conversation page unavailable')
            page.context.new_cdp_session(page).send('Page.setBypassCSP',{'enabled':True})
            page.evaluate('v=>window.__setEditorAuth(v)',{'token':token})
            page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':cid,'playhead':0,'selected':[]})
            page.evaluate("async()=>{$('scope').value='whole';await connect();micOn=true;mic?.getTracks().forEach(t=>t.enabled=false);}")
            print('READY',flush=True)
            last=None
            while not (folder/'stop-observer').exists():
                command=folder/'command.json'
                if not command.exists():page.wait_for_timeout(250);continue
                try:request=json.loads(command.read_text(encoding='utf-8-sig'))
                except ValueError:page.wait_for_timeout(250);continue
                if request.get('id')==last:page.wait_for_timeout(250);continue
                last=request['id'];began=time.monotonic()
                if request.get('voice'):
                    spoken=folder/'spoken.txt';spoken.write_text(request['text'],encoding='utf-8');wav=folder/'spoken.wav'
                    script=f"Add-Type -AssemblyName System.Speech; $synth=New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.SelectVoice('Microsoft Haruka Desktop'); $synth.SetOutputToWaveFile('{wav}'); $synth.Speak([IO.File]::ReadAllText('{spoken}',[Text.Encoding]::UTF8)); $synth.Dispose()"
                    subprocess.run(['powershell','-NoProfile','-EncodedCommand',base64.b64encode(script.encode('utf-16le')).decode()],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
                    page.evaluate("""async b64=>{
                        const ac=new AudioContext();await ac.resume();window.trialAudio=ac;
                        const dest=ac.createMediaStreamDestination();
                        const silent=ac.createBufferSource();silent.buffer=ac.createBuffer(1,48000,48000);silent.loop=true;silent.connect(dest);silent.start();
                        await pc.getSenders().find(s=>s.track?.kind==='audio').replaceTrack(dest.stream.getAudioTracks()[0]);
                        const buffer=await ac.decodeAudioData(Uint8Array.from(atob(b64),c=>c.charCodeAt(0)).buffer);
                        const source=ac.createBufferSource();source.buffer=buffer;source.connect(dest);source.connect(ac.destination);
                        await new Promise(resolve=>{source.onended=resolve;source.start();});
                    }""",base64.b64encode(wav.read_bytes()).decode())
                    # VAD may create idle gaps between sentences. Only observe
                    # completion after the entire test utterance has played.
                    page.wait_for_function('()=>reasonRunning',timeout=60000)
                else:page.evaluate("text=>{$('input').value=text;submit();}",request['text'])
                try:
                    page.wait_for_function('()=>!reasonRunning&&!busy&&!relayActive&&!audioPlaying&&!active&&relayQueue.length===0',timeout=180000)
                    result=page.evaluate('({messages:conversationMemory,jobs:[...jobs],error:$("toast").textContent,presentation:window.__editorPresentation||null})')
                    result.update(id=last,seconds=round(time.monotonic()-began,2))
                except Exception as exc:result={'id':last,'error':str(exc),'seconds':round(time.monotonic()-began,2)}
                (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                page.screenshot(path=str(folder/f'turn-{last}.png'))
                page.evaluate('flushAudit()')
                print('TURN',last,round(time.monotonic()-began,2),flush=True)
            page.evaluate("disconnect('observer_finished')")
    finally:
        proc.terminate();proc.wait(timeout=15)


if __name__=='__main__':main()
