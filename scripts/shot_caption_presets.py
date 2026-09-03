import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests
from app.services.auth_service import create_token_pair
from app.api import production_asset_routes as P
ROOM="bd05fcc0-c143-4d1c-828e-7624e087b6c1"; MAIN="e22695c0-0b77-4413-a2e8-f585739243bc"
APIB="http://127.0.0.1:8000/api/v1/production-assets"; WEB="http://127.0.0.1:3000"
tp=create_token_pair(user_id="2582a188-ff24-4a4f-b989-6063034d90b2", email="0aw325171@gmail.com")
H={"Authorization":f"Bearer {tp.access_token}","Content-Type":"application/json"}; C={"done_access_token":tp.access_token}
seq={"format":"9:16","duration":8.0,"tracks":[
 {"id":"tv","type":"video","clips":[{"id":"V1","asset_id":MAIN,"track":"video","layer":0,"timeline_start":0,"timeline_end":8,"source_start":0,"source_end":8,"composition":"fullscreen","role":"main"}]},
 {"id":"tc","type":"caption","clips":[{"id":"CAP1","track":"caption","layer":0,"timeline_start":0,"timeline_end":8,"text":"渾身のテロップ"}]}]}
content=requests.post(f"{APIB}/contents",headers=H,cookies=C,timeout=30,data=json.dumps({"room_id":ROOM,"title":"PRESET SHOT","format":"9:16","asset_ids":[MAIN],"timeline":{"format":"9:16","source_asset_ids":[MAIN],"annotations":[]}})).json()
cid=content["id"]; P._update_content(ROOM,cid,{"timeline":{"sequence":seq,"annotations":[]}})
out=Path("uploads")/"_preset_shot.png"
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True,channel="chrome"); ctx=b.new_context(viewport={"width":1500,"height":950})
        ctx.add_cookies([{"name":"done_access_token","value":tp.access_token,"url":WEB},{"name":"done_refresh_token","value":tp.refresh_token,"url":WEB}])
        ctx.add_init_script(f"window.localStorage.setItem('done-token', {tp.access_token!r});")
        page=ctx.new_page(); page.goto(f"{WEB}/production-workspace?room_id={ROOM}&content_id={cid}",wait_until="domcontentloaded",timeout=45000)
        page.wait_for_timeout(7000)
        page.query_selector("[data-clip-id='CAP1']").click(); page.wait_for_timeout(500)
        page.query_selector("button[title='黄ポップ']").click(); page.wait_for_timeout(1500)
        page.screenshot(path=str(out)); print("screenshot:", out)
        b.close()
finally:
    cpath=P._room_dir(ROOM)/"contents.json"; data=[c for c in json.loads(cpath.read_text(encoding="utf-8")) if c["id"]!=cid]
    cpath.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8"); print("[cleanup] removed")
