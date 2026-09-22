"""Real conversation replay; preparation dispatch is simulated, no account is touched."""
import json,time,os
from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(bypass_csp=True)
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    calls=[]
    def tool(route):
        data=route.request.post_data_json;calls.append(data)
        result={'ok':True}
        if data['name']=='project_status':result.update(active_count=0,active_jobs=[])
        if data['name']=='delegate_edit':result.update(job_id='simulated-preparation')
        route.fulfill(json=result)
    page.route('**/editor-assistant/tool',tool)
    page.goto('http://127.0.0.1:'+os.getenv('EDITOR_TEST_PORT','8013')+'/api/v1/editor-assistant/page')
    page.evaluate('async()=>{await connect();turn={turn_id:"test",mode:"text",context:{room_id:"test",content_id:"test"}};}')
    messages=[('system','現在の画面は動画エディター。クリップ選択なし、scope_mode=selected。過去のunfinished_workにはHeyGenアカウント確認待ちという記録がある。'),
              ('user','この動画の声をもっとリアルにしたい。HeyGenでクローン音声を作りたいんだけど、できる？'),
              ('assistant','HeyGenは接続待ちなので、先に音声修復をするのが現実的です。'),
              ('user','それを後回しにするんですか？接続の準備から進めてください。')]
    for role,text in messages:
        page.evaluate('(m)=>send({type:"conversation.item.create",item:{type:"message",role:m[0],content:[{type:"input_text",text:m[1]}]}})',[role,text])
    page.evaluate('respond()')
    deadline=time.monotonic()+45
    while time.monotonic()<deadline and not any(c['name']=='delegate_edit' for c in calls):page.wait_for_timeout(250)
    delegated=next((c for c in calls if c['name']=='delegate_edit'),None)
    assert delegated and delegated['args'].get('task_kind')=='prepare',calls
    assert 'HeyGen' in delegated['args']['instruction'] or 'ヘイジェン' in delegated['args']['instruction']
    print('PASS',json.dumps(delegated['args'],ensure_ascii=False))
    page.evaluate('turn=null;disconnect()');browser.close()
