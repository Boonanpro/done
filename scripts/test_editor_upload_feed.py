"""Authenticated upload -> user presentation, with browser picker/drop and reload."""
import base64,json,uuid
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

def main():
    base='http://127.0.0.1:8037';room='upload-feed-'+uuid.uuid4().hex[:8]
    folder=Path('uploads/production-assets')/room;folder.mkdir(parents=True)
    (folder/'contents.json').write_text('[]');(folder/'assets.json').write_text('[]')
    token=(Path.home()/'.done/native_token.txt').read_text().strip()
    client=httpx.Client(base_url=base,headers={'Authorization':'Bearer '+token})
    cid=client.post('/api/v1/editor-assistant/new',json={'room_id':room}).json()['content_id']
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1400,'height':950})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        def setup():
            page.goto(base+'/api/v1/editor-assistant/page')
            page.evaluate('v=>window.__setEditorAuth(v)',{'token':token})
            page.evaluate('c=>window.__updateEditorContext(c)',{'room_id':room,'content_id':cid,'playhead':0,'selected':[]})
        setup()
        page.locator('input[type=file]').set_input_files('scratch/cafe-final-12.png')
        page.wait_for_function('()=>document.querySelector(".reference-card img")?.naturalWidth>0')
        page.wait_for_function('()=>document.querySelector(".presentation-author")?.textContent==="あなた"')
        page.wait_for_function('()=>!document.querySelector("[data-presentation^=upload-]")',timeout=30000)
        assert page.locator('#toast').inner_text()==''
        assert page.locator('#log').inner_text()==''
        history=client.post('/api/v1/editor-assistant/presentations',json={'room_id':room,'content_id':cid}).json()
        assert history['presentations'][0]['author']=='user'
        assert history['presentations'][0]['items'][0]['asset_id']
        # Use a real browser File and the actual DOM drop handler.
        payload=base64.b64encode(Path('scratch/cafe-final-12.png').read_bytes()).decode()
        page.evaluate("""data=>{const bytes=Uint8Array.from(atob(data),c=>c.charCodeAt(0));const dt=new DataTransfer();dt.items.add(new File([bytes],'dropped.png',{type:'image/png'}));document.dispatchEvent(new DragEvent('dragenter',{dataTransfer:dt,bubbles:true}));document.dispatchEvent(new DragEvent('drop',{dataTransfer:dt,bubbles:true,cancelable:true}));}""",payload)
        page.wait_for_function('()=>document.querySelectorAll(".reference-card").length===2 && !document.querySelector("[data-presentation^=upload-]")',timeout=30000)
        assert not page.evaluate('document.body.classList.contains("file-drag")')
        page.locator('input[type=file]').set_input_files('exports/editor-observed-cafe-20260910.mp4')
        page.wait_for_function('()=>document.querySelector(".reference-card video")?.readyState>=2',timeout=30000)
        page.wait_for_function('()=>document.querySelectorAll(".reference-card").length===3 && !document.querySelector("[data-presentation^=upload-]")',timeout=30000)
        page.route('**/production-assets/upload?*',lambda r:r.fulfill(status=503,json={'detail':'test failure'}))
        page.locator('input[type=file]').set_input_files('scratch/cafe-final-12.png')
        page.get_by_text('送信できませんでした',exact=True).wait_for()
        assert page.locator('#toast').inner_text()==''
        page.unroute('**/production-assets/upload?*')
        page.get_by_role('button',name='再試行',exact=True).click()
        page.wait_for_function('()=>document.querySelectorAll(".reference-card").length===4 && !document.querySelector("[data-presentation^=upload-]")',timeout=30000)
        setup()
        latest=client.post('/api/v1/editor-assistant/presentations',json={'room_id':room,'content_id':cid}).json()['presentations'][-1]
        page.evaluate('p=>renderReferences(p)',latest)
        page.wait_for_function('()=>document.querySelectorAll(".reference-card").length===4')
        assert page.locator('.presentation-author').all_text_contents()==['あなた']*4
        assert not errors,errors
        page.screenshot(path='scratch/upload-feed.png')
        browser.close()
    print('PASS picker, drop, real image preview, sender, persistence, no upload toast/chat text')

if __name__=='__main__':main()
