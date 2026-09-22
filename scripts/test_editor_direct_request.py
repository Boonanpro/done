"""Replay the user's request against real conversation inference and simulated tools."""
import json,time
from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(bypass_csp=True)
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    calls=[]
    def tool(route):
        data=route.request.post_data_json;name=data['name'];calls.append(name)
        result={'ok':True}
        if name=='project_status':result.update(active_count=0,active_jobs=[])
        elif name=='delegate_edit':result.update(job_id='simulation-only')
        elif name=='timeline_state':result.update(clips=[{'id':'v1','timeline_start':0,'timeline_end':4,'asset_id':'a1'}])
        route.fulfill(json=result)
    page.route('**/editor-assistant/tool',tool)
    page.goto('http://127.0.0.1:8012/api/v1/editor-assistant/page')
    page.evaluate('async()=>{await connect();turn={turn_id:"test",mode:"text",context:{room_id:"test",content_id:"test"}};send({type:"conversation.item.create",item:{type:"message",role:"system",content:[{type:"input_text",text:"直前の会話では、背景全体をGemini Omni 1.1で白黒の昭和レトロな世界観へ作り替えることで合意済み。直前のproject_status結果はactive_count=0, active_jobs=[]。過去のジョブはfailedで当時のエラーは別ジョブ実行中だった。今は全体が編集対象、scope_mode=whole。"}]}});send({type:"conversation.item.create",item:{type:"message",role:"user",content:[{type:"input_text",text:"ないならできるやん。作れよ。"}]}});respond();}')
    deadline=time.monotonic()+40
    while time.monotonic()<deadline and 'delegate_edit' not in calls:page.wait_for_timeout(250)
    assert 'delegate_edit' in calls,calls
    assert calls.count('project_status')<=1,calls
    print('PASS clear request delegated; calls=',calls)
    page.evaluate('turn=null;disconnect();');browser.close()
