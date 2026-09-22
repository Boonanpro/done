"""Export the current reviewed acceptance project through the conversation UI."""
import json,time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
from app.services import timeline_draft as td,timeline_live as tl

room='assistant-complete-test-8e96bdba';cid='a65ccfdd-6304-4dee-9fa4-c06d79ab921c'
folder=td._room_dir(room);base='http://127.0.0.1:8011/api/v1'
token=(Path.home()/'.done/native_token.txt').read_text().strip()
with sync_playwright() as p,httpx.Client(headers={'Authorization':'Bearer '+token},timeout=30) as client:
    def status():
        r=client.post(base+'/editor-assistant/project-status',json={'room_id':room,'content_id':cid});r.raise_for_status();return r.json()
    old={j['id'] for j in status()['jobs']}
    browser=p.chromium.launch(headless=True);page=browser.new_page()
    page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    page.goto(base+'/editor-assistant/page')
    page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':cid,'playhead':0,'selected':[]})
    page.locator('#scope').select_option('whole')
    page.locator('#input').fill('前の書き出しファイルは使わず、今の動画をもう一度新しい動画ファイルに書き出してください。')
    page.locator('#send').click()
    end=time.monotonic()+300
    while time.monotonic()<end:
        jobs=[j for j in status()['jobs'] if j['id'] not in old]
        if jobs and jobs[0]['status'] in {'done','failed','canceled'}:
            job=jobs[0];assert job['status']=='done',job
            (folder/'refined-export.json').write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8')
            print('EXPORTED',job['result'],flush=True);break
        page.wait_for_timeout(2000)
    else:raise AssertionError('Export did not complete')
    page.locator('#disconnect').click();browser.close()
