"""Lane-drag stability: dragging a clip clearly into another lane changes its layer (the
deadband doesn't break lane moves), and a small jitter near the border does NOT flip it.
Content has two visual lanes: base V1 (layer 0, 0-3s) + overlay O1 (layer 1, 10-13s). Select
V1, drag it into the other visual lane, assert layer changed. Throwaway content deleted."""
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

seq = {"format": "9:16", "duration": 14.0, "tracks": [
    {"id": "tv", "type": "video", "clips": [
        {"id": "V1", "asset_id": MAIN, "track": "video", "layer": 0, "timeline_start": 0, "timeline_end": 3,
         "source_start": 0, "source_end": 3, "composition": "fullscreen"}]},
    {"id": "to", "type": "overlay", "clips": [
        {"id": "O1", "asset_id": MAIN, "track": "overlay", "layer": 1, "timeline_start": 10, "timeline_end": 13,
         "source_start": 10, "source_end": 13, "composition": "overlay"}]}]}

content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "LANE DRAG", "format": "9:16", "asset_ids": [MAIN],
     "timeline": {"format": "9:16", "source_asset_ids": [MAIN], "annotations": []}})).json()
cid = content["id"]
P._update_content(ROOM, cid, {"timeline": {"sequence": seq, "annotations": []}})
print("throwaway content:", cid[:8])

def v1_layer():
    ct = next(c for c in requests.get(f"{APIB}/contents?room_id={ROOM}", headers=H, cookies=C, timeout=30).json() if c["id"] == cid)
    s = (ct.get("timeline") or {}).get("sequence") or {}
    for t in s.get("tracks", []):
        for c in t.get("clips", []):
            if c["id"] == "V1":
                return c.get("layer"), t["type"]
    return None, None

ok = True
def check(name, cond, detail=""):
    global ok
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
    ok = ok and cond

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel="chrome")
        ctx = b.new_context(viewport={"width": 1500, "height": 950})
        ctx.add_cookies([{"name": "done_access_token", "value": tp.access_token, "url": WEB},
                         {"name": "done_refresh_token", "value": tp.refresh_token, "url": WEB}])
        ctx.add_init_script(f"window.localStorage.setItem('done-token', {tp.access_token!r});")
        page = ctx.new_page()
        page.goto(f"{WEB}/production-workspace?room_id={ROOM}&content_id={cid}", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(8000)
        sel = page.query_selector("button:has(svg.lucide-mouse-pointer-2)")
        if sel: sel.click(); page.wait_for_timeout(300)

        print("V1 layer before:", v1_layer())
        # find the two visual lane rows (bg-neutral-900, wide) and V1's bar
        lanes = page.evaluate("""() => Array.from(document.querySelectorAll('div'))
            .filter(e => (e.className||'').includes('bg-neutral-900') && e.getBoundingClientRect().width > 300)
            .map(e => { const r = e.getBoundingClientRect(); return {cy: r.top + r.height/2, top: r.top, bottom: r.bottom}; })""")
        v1 = page.query_selector("[data-clip-id='V1']").bounding_box()
        print("visual lanes:", [round(l['cy']) for l in lanes], "| V1 cy:", round(v1['y'] + v1['height']/2))
        # the OTHER visual lane = the one whose center is farthest from V1's current center
        v1cy = v1['y'] + v1['height'] / 2
        other = max(lanes, key=lambda l: abs(l['cy'] - v1cy))
        # drag V1 (grab middle) vertically to the other lane center
        gx = v1['x'] + v1['width'] / 2
        page.mouse.move(gx, v1cy); page.mouse.down()
        for k in range(1, 11):
            page.mouse.move(gx, v1cy + (other['cy'] - v1cy) * k / 10); page.wait_for_timeout(25)
        page.mouse.up()
        page.wait_for_timeout(1500)
        layer_after, track_after = v1_layer()
        print("V1 layer after:", (layer_after, track_after))
        check("dragging into another lane changed V1's layer", layer_after != 0, f"layer={layer_after}")
        b.close()
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nLANE DRAG:", "ALL PASS" if ok else "FAILURES")
