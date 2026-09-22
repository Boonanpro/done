"""A correction overtakes a delayed tool call; the old edit must not commit."""
import json
import uuid
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
room = 'assistant-interrupt-test-' + uuid.uuid4().hex[:8]
folder = root/'uploads/production-assets'/room
folder.mkdir(parents=True)
seq = {'duration': 3, 'format': '16:9', 'tracks': [{'id':'v','type':'video','clips':[
    {'id':'a','text':'維持する字幕','timeline_start':0,'timeline_end':3}]}]}
(folder/'contents.json').write_text(json.dumps([{'id':'test','timeline':{'sequence':seq}}]),encoding='utf-8')
(folder/'assets.json').write_text('[]')
key=(Path.home()/'.done/native_token.txt').read_text().strip()
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page()
    page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
    # Deliberately deliver authentication AFTER the page script has executed.
    page.evaluate('key=>window.__setEditorAuth({token:key})',key)
    page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':'test','selected':[{'id':'a'}]})
    result=page.evaluate('''async () => {
      const nativeFetch=window.fetch.bind(window);
      const sent=[];dc={readyState:'open',send:s=>sent.push(JSON.parse(s))};
      const track={enabled:true};mic={getTracks:()=>[track],getAudioTracks:()=>[track]};micOn=true;
      await begin(structuredClone(context),'voice');
      window.fetch=async (url,init)=>{
        if(String(url).endsWith('/tool'))await delay(250);
        return nativeFetch(url,init);
      };
      setBusy(true);
      const oldEpoch=epoch;
      const pending=onEvent({type:'response.function_call_arguments.done',call_id:'late',name:'timeline_edit',
        arguments:JSON.stringify({op:'set_clip',args:{clip_id:'a',text:'遅れた指示'}})});
      await delay(25);await startSpeech();await pending;
      return {mic_enabled:track.enabled,interrupted:epoch>oldEpoch,cancel_sent:sent.some(e=>e.type==='response.cancel')};
    }''')
    assert all(result.values()),result
    assert json.loads((folder/'contents.json').read_text(encoding='utf-8'))[0]['timeline']['sequence']==seq
    print('interruption_keeps_mic_and_rejects_late_edit',result)
    browser.close()
