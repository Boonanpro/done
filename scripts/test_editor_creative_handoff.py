"""Real Realtime conversation decision; downstream production is captured, not billed."""
import json
import time
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
        if data['name']=='delegate_edit':result.update(job_id='captured-creative-consultation')
        route.fulfill(json=result)
    page.route('**/editor-assistant/tool',tool)
    page.goto('http://127.0.0.1:8028/api/v1/editor-assistant/page')
    page.evaluate('async()=>{await connect();turn={turn_id:"test",mode:"text",context:{room_id:"test",content_id:"test"}};}')
    messages=[('system','この作品には参考動画ref1が保存済み。制作方針は未決定。'),
        ('user','参考みたいな勢いと見た目で、焼き鳥屋の動画にしたい。仕事帰りに一人でも入りやすそうと思ってほしい。どんな見せ方が良いか、参考を見て考えてほしい。'),
        ('assistant','まず参考の良さを読み取って、焼き鳥屋に合う見せ方を考えます。'),
        ('user','うん。前の無料限定は取り消す。必要ならGoogle直結で5秒一本の見本に1ドルまで使って良い。Higgsのクレジットは使わないで。作り方はそっちで考えて。')]
    for role,text in messages:
        page.evaluate('(m)=>send({type:"conversation.item.create",item:{type:"message",role:m[0],content:[{type:m[0]==="assistant"?"output_text":"input_text",text:m[1]}]}})',[role,text])
    page.evaluate('respond()')
    deadline=time.monotonic()+45
    while time.monotonic()<deadline and not any(c['name']=='delegate_edit' for c in calls):page.wait_for_timeout(250)
    delegated=next((c for c in calls if c['name']=='delegate_edit'),None)
    Path('uploads/creative-handoff-realtime.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2),encoding='utf-8')
    assert delegated,calls
    instruction=delegated['args']['instruction']
    assert 'Google' in instruction or 'グーグル' in instruction
    assert '焼き鳥' in instruction or '焼鳥' in instruction
    print('PASS',json.dumps(delegated['args'],ensure_ascii=False))
    page.evaluate('turn=null;disconnect()');browser.close()
