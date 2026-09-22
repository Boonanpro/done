"""Real Realtime model, voice-context follow-up after seeking, and compositor proof.

Utterances are injected as transcripts; this does not test microphone recognition.
Uses a disposable document and never modifies the user's video.
"""
import base64
import json
import time
import uuid
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image, ImageChops
from app.services import timeline_draft as td, timeline_live as tl, timeline_scope as scope

room='assistant-size-test-'+uuid.uuid4().hex[:8]
folder=td._room_dir(room);folder.mkdir(parents=True)
seq={'duration':150,'format':'16:9','frame_rate':30,'tracks':[{'id':'v','type':'video','clips':[
    {'id':'a','text':'車台番号の欄と、初度登録年月の欄です','timeline_start':101,'timeline_end':105,'style':{'fontSize':.85,'color':'#ffffff'}},
    {'id':'b','text':'弊社最近公式LINEも始めました','timeline_start':133,'timeline_end':136,'style':{'fontSize':.85}}]}]}
(folder/'contents.json').write_text(json.dumps([{'id':'test','title':'サイズと会話の検証','timeline':{'sequence':seq}}],ensure_ascii=False),encoding='utf-8')
(folder/'assets.json').write_text('[]')
def frame(name):
    result=tl.render_frame_b64(room,'test',104,half=False)
    assert result['ok'],result
    path=folder/(name+'.png');path.write_bytes(base64.b64decode(result['image'].split(',',1)[1]))
    return Image.open(path).convert('RGB')
before=frame('before')
token=(Path.home()/'.done/native_token.txt').read_text().strip()
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page()
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
    def say(text,t,cid):
        page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':'test','playhead':t,'selected':[{'id':cid}]})
        started=time.monotonic()
        page.evaluate('''async text=>{
            await connect();await interrupt();setBusy(true);
            const b=await begin(structuredClone(context),'voice',text);
            await addContext(b,epoch);
            send({type:'conversation.item.create',item:{type:'message',role:'user',content:[{type:'input_text',text}]}});
            respond();
        }''',text)
        page.wait_for_function('()=>!busy && !active && !retryTimer',timeout=120000)
        print('TURN',text,'seconds',round(time.monotonic()-started,2),page.locator('#log').inner_text()[-1400:],flush=True)
    say('この字幕もうちょっと大きくしてくれない？サイズを。',104,'a')
    _,one=tl.live_sequence(room,'test');size1=scope.clips(one)['a'][1]['style']['fontSize']
    assert size1>.85
    after=frame('after')
    assert ImageChops.difference(before,after).getbbox(),'saved size did not change rendered image'
    assert scope.clips(one)['b']==scope.clips(seq)['b']
    say('さっきの字幕、まだ小さいからもっと大きくして。',134,'b')
    _,two=tl.live_sequence(room,'test')
    assert scope.clips(two)['a'][1]['style']['fontSize']>size1,'follow-up edited wrong caption'
    assert scope.clips(two)['b']==scope.clips(seq)['b'],'neighbor was changed'
    say('今どの字幕を変えたの？文言を教えて。',134,'b')
    page.evaluate('flushAudit()')
    log=page.locator('#log').inner_text()
    (folder/'conversation.txt').write_text(log,encoding='utf-8')
    assert '車台番号' in log
    say('じゃあ今見ているLINEの字幕も少し大きくして。',134,'b')
    _,three=tl.live_sequence(room,'test')
    assert scope.clips(three)['b'][1]['style']['fontSize']>.85
    assert scope.clips(three)['a']==scope.clips(two)['a'],'new topic remained fixed to old target'
    page.locator('#disconnect').click();browser.close()
print('PASS visual resize, follow-up after seek, named target, explicit new topic',room,flush=True)
