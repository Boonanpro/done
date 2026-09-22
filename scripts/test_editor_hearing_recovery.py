"""Real voice model with text inputs and fixture assets; no production changes."""
import json,uuid,os,tempfile
from app.services import editor_presentation, timeline_draft as td
test_dir=tempfile.TemporaryDirectory(prefix="editor-hearing-")
from pathlib import Path
td.UPLOAD_ROOT=Path(test_dir.name)
folder=td.UPLOAD_ROOT/"hearing-fixture";folder.mkdir()
(folder/"contents.json").write_text(json.dumps([{"id":"fixture","timeline":{"sequence":{"tracks":[]}}}]))
(folder/"assets.json").write_text("[]")
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(bypass_csp=True)
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    page.route('**/editor-assistant/begin',lambda r:r.fulfill(json={'turn_id':uuid.uuid4().hex,'context':dict(r.request.post_data_json,production={},creative_brief={})}))
    def tool(r):
        name=r.request.post_data_json['name']
        result={'ok':True}
        if name=='list_assets':result={'assets':[{'id':'a','name':'本人による問い合わせ案内.mp4','kind':'video','duration':211.5},{'id':'b','name':'工場と車両の紹介.mp4','kind':'video','duration':60}]}
        if name=='delegate_edit':result={'ok':True,'job_id':'fixture-worker','state':'queued','note':'作業を受け付けました。結果は完了時に通知します。'}
        if name=='project_status':result={'ok':True,'active_count':1,'active_jobs':[{'id':'fixture-worker','status':'running'}]}
        if name=='present_references':result=editor_presentation.present('hearing-fixture','fixture',r.request.post_data_json['args']['items'])
        r.fulfill(json=result)
    page.route('**/editor-assistant/tool',tool)
    page.route('**/editor-assistant/cancel',lambda r:r.fulfill(json={'ok':True}))
    page.route('**/editor-assistant/project-status',lambda r:r.fulfill(json={'jobs':[]}))
    page.route('**/editor-assistant/events',lambda r:r.fulfill(json={'ok':True}))
    page.goto(os.getenv('EDITOR_TEST_URL','http://127.0.0.1:8019')+'/api/v1/editor-assistant/page')
    page.evaluate('''()=>{
      window.__updateEditorContext({room_id:'hearing-fixture',content_id:'fixture'});
      window.rows=[];const orig=record;record=(type,data={})=>{rows.push({type,...data});orig(type,data);};
      const original=begin;begin=async(...args)=>{const b=await original(...args);if(b)b.mode='voice';return b;};
    }''')
    def say(text):
        start=page.evaluate('rows.length')
        page.evaluate('(text)=>{document.getElementById("input").value=text;submit();}',text)
        page.wait_for_function('!busy&&!active',timeout=60000)
        events=page.evaluate('(n)=>rows.slice(n)',start)
        spoken=''.join(e.get('text','') for e in events if e['type']=='assistant_transcript')
        used=[e.get('name') for e in events if e['type']=='tool_started']
        print(json.dumps({'user':text,'assistant':spoken,'tools':used},ensure_ascii=False),flush=True)
        return spoken,used
    say('吉川特装のホームページで、修理を問い合わせるお客さんに必要な情報の送り方を案内したい。本人が説明した動画を使って、今の3項目を5項目に増やしたいです。')
    _,used=say('ライブラリにある他の動画も確認して。')
    assert 'list_assets' in used
    page.evaluate("disconnect('test_reopen')")
    spoken,_=say('どんな形式で作るのがいいと思う？')
    assert '何を作りたい' not in spoken and any(s in spoken for s in ['本人','説明','案内','問い合わせ'])
    say('ちょっと待って。思い出してるから黙って待ってて。')
    spoken,used=say('五つ目、何やったかなあ。')
    assert not spoken and 'wait_for_user' in used
    spoken,used=say('ダン、今の動画は誰向けに何を案内するんだっけ？')
    assert spoken and 'resume_conversation' in used and any(s in spoken for s in ['問い合わせ','修理'])
    spoken,used=say('今の音声合成に使えるモデルは何か、設定を調べて教えて。')
    assert 'delegate_edit' in used
    spoken,used=say('文字を大きくして順に出す案と、控えめに出す案がどう違うか、言葉じゃ分からないから実物を見せて。')
    assert 'present_references' in used
    assert page.locator('.proposal-player').count()>0
    page.screenshot(path='uploads/editor-model-proposals.png')
    page.evaluate("disconnect('test_done')");browser.close()
print('PASS library discovery, reconnect context, concrete format suggestion, silent waiting')
