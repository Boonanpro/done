"""Exercise attachment UX in a real browser with mocked network boundaries."""
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1] / 'app' / 'static'
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width':1300, 'height':900})
    errors, uploads, registrations = [], [], []
    page.on('pageerror', lambda e: errors.append(str(e)))

    def route(r):
        u = r.request.url
        files = {'/page':('editor-assistant.html','text/html'),
                 '/proposal-script':('editor-proposals.js','application/javascript'),
                 '/script':('editor-assistant.js','application/javascript')}
        suffix = '/' + u.rsplit('/',1)[-1]
        if suffix in files:
            filename, mime = files[suffix]
            r.fulfill(body=(root/filename).read_text(encoding='utf-8'),content_type=mime)
        elif '/upload?' in u:
            uploads.append(r.request.headers)
            r.fulfill(json={'id':'attached-test','filename':'sample.png'})
        elif u.endswith('/reference'):
            registrations.append(r.request.post_data_json)
            r.fulfill(json={'ok':True})
        else:
            r.fulfill(json={'ok':True})

    page.route('http://localhost:9876/**', route)
    page.add_init_script("window.setInterval=()=>0;window.__editorBootstrap={token:'test'}")
    page.goto('http://localhost:9876/api/v1/editor-assistant/page')
    assert not errors, errors
    page.evaluate("window.__updateEditorContext({room_id:'test',content_id:'test'});flushAudit=async()=>{};")
    page.locator('input[type=file]').set_input_files({'name':'sample.png','mimeType':'image/png','buffer':b'fixture'})
    page.wait_for_function("document.getElementById('toast').textContent==='素材を追加しました'")
    assert page.get_by_role('button',name='素材を渡す').is_enabled()
    assert uploads[0]['authorization'] == 'Bearer test'
    assert registrations == [{'room_id':'test','content_id':'test','source':'attached-test'}]
    assert not page.locator('#mic').evaluate("e=>e.classList.contains('live')")
    assert not errors, errors
    page.screenshot(path='uploads/reference-analysis-20260908/attachment-ui.png')
    browser.close()
print('PASS picker, authenticated upload, reference registration, microphone unchanged')
