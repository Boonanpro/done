"""Real conversation model -> real proposal store/player -> selection -> worker receipt.

Only the production worker is simulated; no paid media generation or real user room writes.
"""
import json,tempfile,time,uuid
from pathlib import Path
from playwright.sync_api import sync_playwright
from app.services import editor_presentation as proposals,timeline_draft as td

with tempfile.TemporaryDirectory(prefix='proposal-conversation-') as directory,sync_playwright() as p:
    td.UPLOAD_ROOT=Path(directory);folder=td.UPLOAD_ROOT/'fixture';folder.mkdir()
    (folder/'contents.json').write_text(json.dumps([{'id':'c','timeline':{'sequence':{'tracks':[]}}}]))
    (folder/'assets.json').write_text('[]')
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={'width':1280,'height':720},bypass_csp=True)
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    page.route('**/editor-assistant/begin',lambda r:r.fulfill(json={'turn_id':uuid.uuid4().hex,'context':dict(r.request.post_data_json,production={},creative_brief={})}))
    calls=[]
    def tool(r):
        request=r.request.post_data_json;name=request['name'];args=request['args'];calls.append((name,args))
        if name=='present_references':result=proposals.present('fixture','c',args['items'])
        elif name=='choose_reference':result=proposals.choose('fixture','c',args['item_id'],args.get('feedback',''))
        elif name=='delegate_edit':result={'ok':True,'job_id':'worker','state':'queued','note':'制作を受け付けました。完了時に通知します。'}
        else:result={'ok':True}
        r.fulfill(json=result)
    page.route('**/editor-assistant/tool',tool)
    for route in ['cancel','events']:page.route('**/editor-assistant/'+route,lambda r:r.fulfill(json={'ok':True}))
    page.route('**/editor-assistant/project-status',lambda r:r.fulfill(json={'jobs':[]}))
    page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
    page.evaluate("window.__updateEditorContext({room_id:'fixture',content_id:'c'});window.rows=[];const originalRecord=record;record=(type,data={})=>{rows.push({type,...data});originalRecord(type,data);};")
    def say(text):
        started=time.monotonic()
        page.evaluate('(s)=>{document.getElementById("input").value=s;submit();}',text)
        page.wait_for_function('!busy&&!active&&!retryTimer',timeout=90000)
        print(json.dumps({'seconds':round(time.monotonic()-started,2),'user':text,'spoken':page.evaluate("rows.filter(e=>e.type==='assistant_transcript').map(e=>e.text)")},ensure_ascii=False),flush=True)
    say('修理を問い合わせる人が、情報をどう送るか迷わない動画にしたい。大きな文字を順に出す案と、小さく控えめに出す案の違いを、まず無料の動く文字見本で実物を見せて。まだ本編は作らないで。')
    assert any(n=='present_references' for n,_ in calls)
    assert page.locator('.proposal-player').count()==1
    control=page.locator('.proposal-controls button')
    assert control.bounding_box()['y']<620
    page.screenshot(path='uploads/editor-model-proposals.png')
    calls.clear()
    say('１つ目の案で行こう。それを使った通しの下書きに進めて。生成動画にはお金を使わず、今の文字と図形で作って。')
    assert any(n=='choose_reference' for n,_ in calls)
    assert any(n=='delegate_edit' for n,_ in calls)
    assert td._read_contents_raw('fixture')[0].get('chosen_proposal')
    page.evaluate("disconnect('test_done')");browser.close()
print('PASS real proposal generation/display, visible controls, persisted choice, draft handoff receipt')
