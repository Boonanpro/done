"""Drive the real production editor with Playwright to SEE whether the pop-out overlay shows in
the preview, and capture the browser console. This gives the terminal agent eyes on the client
side (which server logs can't). Prints console/page errors + writes a screenshot.
"""
import sys, json, time
sys.path.insert(0, ".")
import requests
from app.services.auth_service import create_token_pair

WEB = "http://127.0.0.1:3000"
APIB = "http://127.0.0.1:8000/api/v1/production-assets"
ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
BASE = "535e2cc4-e200-40c3-b8f1-ade7c5cd3833"    # background (fullscreen)
PERSON = "e22695c0-0b77-4413-a2e8-f585739243bc"  # person -> popout wipe
SHOT = r"C:\Users\Owner\AppData\Local\Temp\claude\D--done\5f4272ef-b5c1-4055-825b-87a714d0efe4\scratchpad\preview_shot.png"

tp = create_token_pair(user_id="2582a188-ff24-4a4f-b989-6063034d90b2", email="0aw325171@gmail.com")
H = {"Authorization": f"Bearer {tp.access_token}", "Content-Type": "application/json"}
C = {"done_access_token": tp.access_token}

seq = {"format": "9:16", "tracks": [
    {"type": "video", "clips": [{"id": "base1", "asset_id": BASE, "track": "video",
        "composition": "fullscreen", "timeline_start": 0, "timeline_end": 3, "source_start": 0, "source_end": 3}]},
    {"type": "overlay", "clips": [{"id": "pop1", "asset_id": PERSON, "track": "overlay", "composition": "pip", "layer": 1,
        "timeline_start": 0, "timeline_end": 4, "source_start": 203.527, "source_end": 207.754,
        "position": {"x": 0.3, "y": 0.655, "width": 0.4, "height": 0.3},
        "effects": [{"type": "popout", "params": {"intensity": "dramatic"}}]}]},
]}

# create content with this timeline
r = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, json={
    "room_id": ROOM, "title": "POPOUT DEBUG", "format": "9:16", "asset_ids": [BASE, PERSON]})
r.raise_for_status(); cid = r.json()["id"]
requests.patch(f"{APIB}/contents/{cid}?room_id={ROOM}", headers=H, cookies=C, timeout=30,
               json={"timeline": {"sequence": seq}}).raise_for_status()
print("content:", cid)

from playwright.sync_api import sync_playwright
logs = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, channel="chrome")
    ctx = b.new_context(viewport={"width": 1500, "height": 950})
    ctx.add_cookies([{"name": "done_access_token", "value": tp.access_token, "url": WEB},
                     {"name": "done_refresh_token", "value": tp.refresh_token, "url": WEB}])
    ctx.add_init_script(f"window.localStorage.setItem('done-token', {tp.access_token!r});")
    page = ctx.new_page()
    page.on("console", lambda m: logs.append(f"[{m.type}] {m.text}"[:300]))
    page.on("pageerror", lambda e: logs.append(f"[pageerror] {e}"[:300]))
    page.on("requestfailed", lambda req: logs.append(f"[reqfailed] {req.url} {req.failure}"[:200]) if "popout" in req.url else None)
    page.goto(f"{WEB}/production-workspace?room_id={ROOM}&content_id={cid}", wait_until="domcontentloaded", timeout=60000)
    # wait for the editor + overlay prepare (generation ~30-60s) + a couple of settle cycles
    for i in range(14):
        time.sleep(5)
        vids = page.evaluate("() => Array.from(document.querySelectorAll('video')).map(v => ({src:(v.currentSrc||v.getAttribute('src')||'').slice(-45), w:v.videoWidth, h:v.videoHeight, rt:v.readyState, paused:v.paused, disp:getComputedStyle(v).display, r:Math.round(v.getBoundingClientRect().width)+'x'+Math.round(v.getBoundingClientRect().height)}))")
        print(f"  t={i*5}s ALLVIDEOS={json.dumps(vids, ensure_ascii=False)}")
        pop = [v for v in vids if 'popout' in (v.get('src') or '')]
        if pop:
            print("POPOUT VIDEO ELEMENT:", json.dumps(pop, ensure_ascii=False)[:500])
            break
        prep = page.evaluate("() => document.body.innerText.includes('準備中')")
        done = page.evaluate("() => document.body.innerText.includes('プレビュー準備完了')")
        print(f"  t={i*5}s videos={len(vids)} popout_el={len(pop)} 準備中={prep} 準備完了={done}")
    page.screenshot(path=SHOT, full_page=False)
    print("screenshot:", SHOT)
    b.close()

print("\n=== CONSOLE (popout/error only) ===")
for l in logs:
    if any(k in l.lower() for k in ["[pop", "popout", "error", "fail", "500", "warn"]):
        print(l)
