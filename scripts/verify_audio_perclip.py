"""Audio collision fix: audio elements must be per-CLIP (not per-asset), so two overlapping
audio clips from the same asset don't fight over one element. Content: V1+A1 (0-20, MAIN) and
an overlapping V2+A2 (5-12, MAIN). Expect 4 hidden MAIN <video> elements (2 video layers +
2 audio); asset-keyed audio would give only 3. Throwaway content deleted afterward."""
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

seq = {"format": "9:16", "duration": 20.0, "tracks": [
    {"id": "tv", "type": "video", "clips": [
        {"id": "V1", "asset_id": MAIN, "track": "video", "layer": 0, "timeline_start": 0, "timeline_end": 20,
         "source_start": 0, "source_end": 20, "composition": "fullscreen", "link_id": "L1"},
        {"id": "V2", "asset_id": MAIN, "track": "video", "layer": 1, "timeline_start": 5, "timeline_end": 12,
         "source_start": 30, "source_end": 37, "composition": "overlay", "link_id": "L2"}]},
    {"id": "ta", "type": "audio", "clips": [
        {"id": "A1", "asset_id": MAIN, "track": "audio", "layer": 0, "timeline_start": 0, "timeline_end": 20,
         "source_start": 0, "source_end": 20, "role": "dialogue", "link_id": "L1"},
        {"id": "A2", "asset_id": MAIN, "track": "audio", "layer": 0, "timeline_start": 5, "timeline_end": 12,
         "source_start": 30, "source_end": 37, "role": "dialogue", "link_id": "L2"}]}]}

content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "AUDIO PERCLIP", "format": "9:16", "asset_ids": [MAIN],
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
        n_main = page.evaluate("""() => Array.from(document.querySelectorAll('video'))
            .filter(v => v.style.display === 'none' && /e22695c0/.test(v.currentSrc || v.src || '')).length""")
        print("hidden MAIN <video> elements:", n_main)
        check("per-clip audio elements (>=4: 2 video + 2 audio, not 3)", n_main >= 4, f"count={n_main}")
        b.close()
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nAUDIO PER-CLIP:", "ALL PASS" if ok else "FAILURES")
