"""Real Realtime model; isolated UI, simulated worker, no account or video writes."""
import json, uuid
from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(bypass_csp=True)
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    calls=[]
    q={'id':'q1','job_id':'j','text':'HeyGenの登録には普段のGoogleアカウントを使ってよいですか？'}
    status={'jobs':[{'id':'j','status':'running','question':q}]}
    production={'active_count':1,'active_jobs':[{'id':'j','status':'running','question':q}], 'latest_finished_job':None}
    def begin(route):
        body=route.request.post_data_json
        route.fulfill(json={'turn_id':uuid.uuid4().hex,'context':dict(body,production=production,
            creative_brief={},selected=[{'text':'朝の光が、やわらかい時間'}],visible_targets=[{'id':'shop'}]),'can_edit':True})
    def tool(route):
        body=route.request.post_data_json;calls.append(body)
        route.fulfill(json={'ok':True,**production} if body['name']=='project_status' else {'ok':True})
    def answer(route):
        calls.append({'name':'answer_question','args':route.request.post_data_json})
        status['jobs'][0]['question']=None
        route.fulfill(json={'ok':True})
    page.route('**/editor-assistant/begin',begin)
    page.route('**/editor-assistant/tool',tool)
    page.route('**/editor-assistant/answer',answer)
    page.route('**/editor-assistant/project-status',lambda r:r.fulfill(json=status))
    page.route('**/editor-assistant/events',lambda r:r.fulfill(json={'ok':True}))
    page.goto('http://127.0.0.1:8015/api/v1/editor-assistant/page')
    page.evaluate('context={room_id:"test",content_id:"test"};flushAudit=async()=>{};')
    page.evaluate('()=>{window.testEvents=[];const original=record;record=(type,data={})=>{testEvents.push({type,...data});original(type,data);};}')
    page.evaluate('()=>{const original=begin;begin=async(...args)=>{const b=await original(...args);if(b)b.mode="voice";return b;};}')
    page.evaluate('(s)=>renderProductionStatus(s,context)',status)
    def say(text):
        offset=page.evaluate('testEvents.length')
        page.locator('#input').fill(text)
        page.evaluate('submit()')
        page.wait_for_function('!busy&&!active',timeout=60000)
        rows=page.evaluate('(n)=>testEvents.slice(n)',offset)
        spoken=' '.join(e.get('text','') for e in rows if e['type']=='assistant_transcript')
        print(json.dumps({'user':text,'assistant':spoken,'tools':[e.get('name') for e in rows if e['type']=='tool_started']},ensure_ascii=False),flush=True)
        assert not any(word in spoken for word in ('店の外観','朝の光','鉢植え'))
        assert len(spoken)<260,spoken
        assert not any(e.get('name') in ('read_editor_context','timeline_frame') for e in rows)
        return rows
    say('説明が長い。今は静かにして。')
    assert page.evaluate('notificationsPaused') and not calls
    say('そのメールって何のために使うの？')
    assert not any(c['name']=='answer_question' for c in calls)
    say('HeyGenの登録には普段のGoogleアカウントを使っていいです。')
    assert len([c for c in calls if c['name']=='answer_question'])==1
    production['active_jobs']=[{'id':'j','status':'running','events':[{'text':'HeyGenの無料アカウント作成とログインが完了。音声クローン作成画面で素材を確認中。'}]}]
    rows=say('HeyGenのログインはどうなった？')
    spoken=' '.join(e.get('text','') for e in rows if e['type']=='assistant_transcript')
    assert '完了' in spoken or 'ログインでき' in spoken
    assert not any(c['name']=='delegate_edit' for c in calls)
    page.evaluate('disconnect()');browser.close()
print('PASS silence, follow-up question, actual answer, current progress without unsolicited screen narration')
