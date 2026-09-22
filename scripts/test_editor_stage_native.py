"""Native full-stage microphone entry with synthetic silence and disposable content."""
import json,os,subprocess,time,uuid,wave,socket
from pathlib import Path
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
room='stage-native-'+uuid.uuid4().hex[:8]
folder=root/'uploads/production-assets'/room;folder.mkdir(parents=True)
(folder/'contents.json').write_text(json.dumps([{'id':'seed','title':'Stage test','room_id':room,'created_at':'2026-09-07T00:00:00Z','updated_at':'2026-09-07T00:00:00Z','timeline':{'format':'16:9','sequence':{'duration':0,'format':'16:9','tracks':[]}}}]),encoding='utf-8')
(folder/'assets.json').write_text('[]',encoding='utf-8')
silence=folder/'silence.wav'
with wave.open(str(silence),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(b'\0\0'*48000*90)
exe=root/'scripts/poc/production_desktop/native_ui/target/release/native_ui.exe'
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
env={**os.environ,'DONE_EDITOR_VOICE':'1','WEBVIEW2_USER_DATA_FOLDER':str(folder/'webview'),
     'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS':f'--remote-debugging-port={port} --use-fake-ui-for-media-stream --use-fake-device-for-media-stream --use-file-for-fake-audio-capture='+str(silence)}
proc=subprocess.Popen([str(exe),str(folder/'contents.json'),str(folder),'--library'],env=env,creationflags=subprocess.CREATE_NO_WINDOW,stdout=subprocess.DEVNULL,stderr=(folder/'native.log').open('w'))
try:
    with sync_playwright() as p:
        browser=None
        for _ in range(80):
            try:browser=p.chromium.connect_over_cdp(f'http://127.0.0.1:{port}');break
            except Exception:time.sleep(.3)
        assert browser,'Native WebView unavailable'
        page=None
        for _ in range(80):
            if browser.contexts:browser.contexts[0].cookies()
            page=next((x for c in browser.contexts for x in c.pages if 'editor-assistant/page' in x.url),None)
            if page:break
            time.sleep(.25)
        assert page,f'Stage missing: {[x.url for c in browser.contexts for x in c.pages]}'
        cdp=page.context.new_cdp_session(page)
        def wait(expression):
            for _ in range(240):
                result=cdp.send('Runtime.evaluate',{'expression':expression,'returnByValue':True})
                if result.get('result',{}).get('value'):return
                page.wait_for_timeout(250)
            raise AssertionError(cdp.send('Runtime.evaluate',{'expression':'JSON.stringify({context,state:document.getElementById("state").textContent,toast:document.getElementById("toast").textContent})','returnByValue':True}))
        wait('typeof micOn!=="undefined"&&micOn&&context?.content_id')
        cid=page.evaluate('context.content_id')
        assert cid!='seed','Entry must create a new project from the library'
        assert page.evaluate('dc.readyState==="open"&&!document.body.classList.contains("compact")')
        initial=page.evaluate('connectedAt')
        page.screenshot(path=str(folder/'stage.png'))
        page.evaluate('renderReferences({id:"live-video",items:[{title:"Motion reference",kind:"video",url:"https://raw.githubusercontent.com/Tejashmakwana/astra-chatgpt-hyperframes/main/examples/chatgpt-blue.mp4",start:1,end:5}]})')
        wait('document.querySelector("video")?.readyState>=1')
        print('native reference media loaded',page.locator('video').evaluate('(v)=>({width:v.videoWidth,height:v.videoHeight,duration:v.duration})'),flush=True)
        page.locator('#edit-view').click()
        wait('document.body.classList.contains("compact")&&innerWidth<600')
        assert page.evaluate('micOn&&connectedAt')==initial
        page.locator('#edit-view').click()
        wait('!document.body.classList.contains("compact")&&innerWidth>600')
        assert page.evaluate('micOn&&connectedAt')==initial
        page.evaluate('disconnect()')
        print('PASS native library -> new project -> live mic -> editor -> full stage, same voice connection',room,flush=True)
finally:
    proc.terminate();proc.wait(timeout=15)
