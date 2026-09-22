"""Real browser rendering of local proposals; no model or generation calls."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from app.services.editor_presentation import clean_composition

composition=clean_composition('unused',{'duration':4,'background':'#162333','layers':[
    {'type':'rect','x':100,'y':160,'width':1080,'height':360,'background':'#245e68','borderRadius':24},
    {'type':'text','text':'必要な情報を、ひとつずつ。','x':140,'y':230,'width':1000,'height':180,
     'fontSize':62,'keyframes':[{'offset':0,'opacity':0,'y':24},{'offset':.3,'opacity':1,'y':0},{'offset':1,'opacity':1}]}]})
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.add_init_script("window.setInterval=()=>0;window.__editorBootstrap={token:'fixture'}")
    page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
    page.evaluate('''p=>{flushAudit=async()=>{};cancelTurn=async()=>{};
      window.__updateEditorContext({room_id:'proposal-test',content_id:'one'});
      renderReferences(p);
    }''',{'id':'p','items':[{'id':'a','title':'文字と動きの実物','kind':'composition','composition':composition},
        {'id':'b','title':'別のコピー','kind':'text','text':'撮って送る。修理が進む。'}]})
    page.locator('.proposal-controls button').click()
    page.locator('.proposal-controls input').fill('2')
    page.locator('.proposal-controls input').dispatch_event('input')
    assert page.locator('.proposal-layer').last.evaluate('(e)=>getComputedStyle(e).opacity')=='1'
    assert page.locator('.proposal-player').bounding_box()['width']>900
    page.wait_for_timeout(300)
    page.screenshot(path='uploads/editor-proposal-preview.png')
    page.get_by_role('button',name='提案を大きく見る').click()
    assert page.locator('.proposal-viewport').bounding_box()['height']>800
    page.get_by_role('button',name='戻る',exact=True).click()
    page.get_by_role('button',name='並べて比べる').click()
    assert page.locator('.proposal-player').count()==2
    page.get_by_role('button',name='１つずつ見る').click()
    chosen=[]
    page.route('**/editor-assistant/choose',lambda r:(chosen.append(r.request.post_data_json),r.fulfill(json={'ok':True})))
    page.evaluate("submit=()=>{window.requested=document.getElementById('input').value;}")
    page.get_by_role('button',name='この方向で下書きを作る').click()
    page.wait_for_timeout(100)
    assert chosen[0]['item_id']=='a'
    assert page.evaluate("requested.includes('通しの下書き')")
    page.evaluate("window.__updateEditorContext({room_id:'other',content_id:'two'})")
    assert page.locator('.proposal-player').count()==0
    assert not errors,errors
    browser.close()
print('PASS animated preview, seek, large display, comparison, selected direction, room cleanup')
