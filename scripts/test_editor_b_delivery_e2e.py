"""Realtime -> actual editor tools/worker -> saved B timeline; no new media generation."""
import copy,json,shutil,time,uuid
from pathlib import Path
from playwright.sync_api import sync_playwright
from app.services import timeline_draft as td,editor_references

state=json.loads(Path('uploads/google-handoff-latest.json').read_text())
source=state['room_id'];room='b-delivery-'+uuid.uuid4().hex[:8]
folder=td._room_dir(room);folder.mkdir(parents=True)
content=copy.deepcopy(td._read_contents_raw(source)[0]);cid=content['id']
seq=td._content_sequence(content)
aid=next(c['asset_id'] for t in seq['tracks'] if t['type']=='video' for c in t['clips'])
content['timeline']={'format':'16:9','sequence':{'format':'16:9','frame_rate':30,'duration':0,'tracks':[{'id':'v','type':'video','clips':[]},{'id':'a','type':'audio','clips':[]}]}}
content['creative_brief']['chosen_sample']={'name':'B','asset_id':aid,'purpose':'日本がブラジルに勝つ架空のコラージュ','feedback':'AよりBが高品質とユーザーが評価。B全尺をエディターで編集したい。'}
td._write_contents_raw(room,[content]);shutil.copy2(td._room_dir(source)/'assets.json',folder/'assets.json')
for f in editor_references._folder(source).glob('*'):
    if f.is_file():shutil.copy2(f,editor_references._folder(room)/f.name)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True);page=browser.new_page(bypass_csp=True)
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
    page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':cid,'playhead':0,'selected':[]})
    page.evaluate('async()=>{await connect();micOn=true;}')
    start=time.monotonic()
    page.evaluate("()=>{$('input').value='さっき選んだBを、この空の動画に音付きで全部入れて、ここで編集できるようにして。既にできたBを使って。新しく生成しなくて良い。';submit();}")
    deadline=start+300
    while time.monotonic()<deadline:
        current=td._content_sequence(td._read_contents_raw(room)[0])
        if current.get('duration',0)>4.9:
            # Allow the completion notification to enter the live conversation.
            page.wait_for_timeout(8000)
            break
        page.wait_for_timeout(1000)
    else:raise AssertionError('No timeline delivery within 300 seconds')
    assert any(t['type']=='audio' and t['clips'] for t in current['tracks'])
    assert current['format']=='16:9'
    log=page.evaluate('({audit,notices:completionNotices,activeNotice})')
    report={'room_id':room,'content_id':cid,'elapsed_seconds':round(time.monotonic()-start,2),'duration':current['duration'],'voice_state':log}
    (folder/'e2e-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    Path('uploads/b-delivery-latest.json').write_text(json.dumps({'room_id':room,'content_id':cid}),encoding='utf-8')
    print('PASS',room,'duration',current['duration'],'seconds',report['elapsed_seconds'],flush=True)
    page.evaluate('disconnect()');browser.close()
