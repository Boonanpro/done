"""#2: the preview must show the ACTIVE clip's correct source frame, even when consecutive
clips jump far apart in source time (as after a tight re-cut). Content: V1 (source 0-3) then
V2 (source 60-63). While V2 is active, the playing video element's currentTime must be in V2's
source range (~60), not stuck near V1's (~3) — a stale frame = the 'wrong/next clip shows' bug."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests
from app.services.auth_service import create_token_pair
from app.api import production_asset_routes as P

ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
MAIN = "e22695c0-0b77-4413-a2e8-f585739243bc"
APIB = "http://127.0.0.1:8000/api/v1/production-assets"
WEB = "http://127.0.0.1:3000"
tp = create_token_pair(user_id="2582a188-ff24-4a4f-b989-6063034d90b2", email="0aw325171@gmail.com")
H = {"Authorization": f"Bearer {tp.access_token}", "Content-Type": "application/json"}
C = {"done_access_token": tp.access_token}

seq = {"format": "9:16", "duration": 6.0, "tracks": [
    {"id": "tv", "type": "video", "clips": [
        {"id": "V1", "asset_id": MAIN, "track": "video", "layer": 0, "timeline_start": 0, "timeline_end": 3,
         "source_start": 0, "source_end": 3, "composition": "fullscreen"},
        {"id": "V2", "asset_id": MAIN, "track": "video", "layer": 0, "timeline_start": 3, "timeline_end": 6,
         "source_start": 60, "source_end": 63, "composition": "fullscreen"}]}]}

content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "VIDEO SEEK TEST", "format": "9:16", "asset_ids": [MAIN],
     "timeline": {"format": "9:16", "source_asset_ids": [MAIN], "annotations": []}})).json()
cid = content["id"]
P._update_content(ROOM, cid, {"timeline": {"sequence": seq, "annotations": []}})
print("throwaway content:", cid[:8])

ok = True
def check(name, cond, detail=""):
    global ok
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
    ok = ok and cond

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel="chrome", args=["--autoplay-policy=no-user-gesture-required"])
        ctx = b.new_context(viewport={"width": 1500, "height": 950})
        ctx.add_cookies([{"name": "done_access_token", "value": tp.access_token, "url": WEB},
                         {"name": "done_refresh_token", "value": tp.refresh_token, "url": WEB}])
        ctx.add_init_script(f"window.localStorage.setItem('done-token', {tp.access_token!r});")
        page = ctx.new_page()
        page.goto(f"{WEB}/production-workspace?room_id={ROOM}&content_id={cid}", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(8000)
        page.mouse.click(750, 400)
        page.keyboard.press("Space")  # play from 0
        # wait until we're inside V2's range (t ~ 3.5-5.5s)
        page.wait_for_timeout(4200)
        # sample the PLAYING video element's currentTime a few times while V2 is active
        cur = []
        for _ in range(6):
            page.wait_for_timeout(120)
            v = page.evaluate("""() => { const a = Array.from(document.querySelectorAll('video'))
                .filter(v => v.style.display==='none' && /e22695c0/.test(v.currentSrc||v.src||'') && !v.paused);
                return a.length ? Math.max(...a.map(x=>x.currentTime)) : null; }""")
            if v is not None:
                cur.append(round(v, 2))
        print("playing video element currentTime while V2 active:", cur)
        b.close()

    inrange = [c for c in cur if c >= 55]   # V2 source ~60-63
    check("playing video element is in V2's source range (~60), not stuck at V1 (~3)",
          len(inrange) >= max(1, len(cur) // 2), f"samples={cur}")
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nVIDEO SEEK:", "ALL PASS" if ok else "FAILURES")
