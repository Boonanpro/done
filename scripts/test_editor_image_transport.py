"""Large reference images must reach Realtime without closing the data channel."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from app.services.editor_project import asset_image

token=(Path.home()/'.done/native_token.txt').read_text().strip()
reference=asset_image('a3970e0b-f7dc-472e-ad63-e8c51382ddb3','3262d616-e55f-414d-a703-16b92077d16b')['image']
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page();page.add_init_script('window.__editorBootstrap='+json.dumps({'token':token}))
    page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
    result=page.evaluate('''async image=>{
        await connect();await addPicture(image,'参照画像');
        await new Promise(r=>setTimeout(r,2000));
        return {channel:dc?.readyState,transport:audit.filter(e=>e.type==='image_transport').at(-1),errors:audit.filter(e=>e.type==='channel_error')};
    }''',reference)
    print(result,flush=True)
    assert result['channel']=='open' and not result['errors']
    assert result['transport']['sentBytes']<64000
    page.evaluate('disconnect()');browser.close()
