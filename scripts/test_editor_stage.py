"""Stage presentation, independent of the user's microphone and video."""
from pathlib import Path
from playwright.sync_api import sync_playwright

out=Path('uploads/editor-stage-review');out.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    page=b.new_page(viewport={'width':1440,'height':900})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8016/api/v1/editor-assistant/page')
    page.wait_for_timeout(400)
    assert not page.locator('#drawer').is_visible()
    page.screenshot(path=str(out/'entry.png'))
    # Reference embeds use bounded playback and appear beside the agent.
    page.route('https://www.youtube-nocookie.com/**',lambda r:r.fulfill(content_type='text/html',body='<body style="background:#292e36;color:#cad0db;font:24px sans-serif;display:grid;place-items:center;height:100%;margin:0">Reference preview</body>'))
    page.evaluate('()=>{context={room_id:"test",content_id:"test"};renderReferences({id:"p",items:[{title:"静かな朝の空気",note:"余白とゆっくりしたカメラの動き",kind:"video",url:"https://youtu.be/dT5-x3u5nCg",start:12,end:18}]});}')
    page.wait_for_timeout(700)
    assert page.locator('.reference-card').count()==1
    assert 'start=12&end=18' in page.locator('iframe').get_attribute('src')
    page.screenshot(path=str(out/'reference.png'))
    page.locator('#show-chat').click();assert page.locator('#input').is_visible()
    page.locator('#input').fill('テキストでも相談する')
    page.locator('#hide-chat').click();assert not page.locator('#drawer').is_visible()
    page.evaluate('window.__setStageMode(false)')
    page.set_viewport_size({'width':355,'height':900})
    page.wait_for_timeout(400);page.screenshot(path=str(out/'compact.png'))
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.locator('#hide-references').click();assert not page.locator('#references').is_visible()
    assert not errors,errors
    b.close()
print('PASS stage, reference interval, drawer, compact layout; screenshots:',out)
