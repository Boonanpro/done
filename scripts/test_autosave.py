"""Verify debounced auto-save: drag a clip, wait for the debounce, and confirm the
backend content.json picked up the new clip position (so a refresh would keep it)."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.auth_service import create_token_pair

USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"
EMAIL = "0aw325171@gmail.com"
ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
CONTENT = "68ab4fe4-6f96-4f72-b085-f818fae83a8d"
BASE = "http://127.0.0.1:3000"
URL = f"{BASE}/production-workspace?room_id={ROOM}&content_id={CONTENT}"

def fx_ts(seq):
    for tr in seq.get("tracks", []):
        for c in tr.get("clips", []):
            if c.get("id") == "fx_blur_setup_pw":
                return c.get("timeline_start")
    return None

room_dir = Path("D:/done/uploads/production-assets") / ROOM
cpath = room_dir / "contents.json"
before = json.loads(cpath.read_text(encoding="utf-8"))
content = next(c for c in before if c["id"] == CONTENT)
print("[as] backend fx_blur_setup_pw.timeline_start BEFORE:", fx_ts(content.get("timeline", {}).get("sequence", {})))

tp = create_token_pair(user_id=USER_ID, email=EMAIL)
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1400, "height": 900})
    ctx.add_cookies([{ "name":"done_access_token","value":tp.access_token,"url":BASE},
                     {"name":"done_refresh_token","value":tp.refresh_token,"url":BASE}])
    ctx.add_init_script(f"window.localStorage.setItem('done-token', {tp.access_token!r});")
    page = ctx.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(7000)
    el = page.evaluate_handle("() => Array.from(document.querySelectorAll('div')).find(e=>{const c=(e.className||'').toString(); return c.includes('cursor-grab')&&c.includes('gap-1');})||null").as_element()
    if not el:
        print("[as] no clip body found"); sys.exit(1)
    bx = el.bounding_box()
    cx, cy = bx["x"]+bx["width"]/2, bx["y"]+bx["height"]/2
    page.mouse.move(cx, cy); page.mouse.down()
    for i in range(1, 11): page.mouse.move(cx + 260*i/10, cy, steps=1); page.wait_for_timeout(22)
    page.mouse.up()
    print("[as] dragged; waiting 2.5s for debounced auto-save (1.2s) + PATCH...")
    page.wait_for_timeout(2500)
    b.close()

after = json.loads(cpath.read_text(encoding="utf-8"))
content2 = next(c for c in after if c["id"] == CONTENT)
ts_after = fx_ts(content2.get("timeline", {}).get("sequence", {}))
print("[as] backend fx_blur_setup_pw.timeline_start AFTER:", ts_after)
print("[as] PERSISTED =", ts_after is not None and abs(float(ts_after) - 28) > 1)

# restore original content to not corrupt the user's data
cpath.write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")
print("[as] restored contents.json to original")
