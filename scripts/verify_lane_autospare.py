"""#1: a clip on the ONLY lane in its zone must still be movable up/down — because there is
now always a spare empty lane. Content has a single video clip (one used video lane). Assert
there are >=2 visual lanes (used + spare) and the clip can be dragged to the spare (layer 0->1)."""
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
    {"id": "tv", "type": "video", "clips": [{"id": "V1", "asset_id": MAIN, "track": "video", "layer": 0,
        "timeline_start": 0, "timeline_end": 5, "source_start": 0, "source_end": 5, "composition": "fullscreen"}]}]}

content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "LANE AUTOSPARE", "format": "9:16", "asset_ids": [MAIN],
     "timeline": {"format": "9:16", "source_asset_ids": [MAIN], "annotations": []}})).json()
cid = content["id"]
P._update_content(ROOM, cid, {"timeline": {"sequence": seq, "annotations": []}})
print("throwaway content:", cid[:8])

def v1_layer():
    ct = next(c for c in requests.get(f"{APIB}/contents?room_id={ROOM}", headers=H, cookies=C, timeout=30).json() if c["id"] == cid)
    for t in (ct.get("timeline") or {}).get("sequence", {}).get("tracks", []):
        for c in t.get("clips", []):
            if c["id"] == "V1":
                return c.get("layer")
    return None

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
        lanes = page.evaluate("""() => Array.from(document.querySelectorAll('div'))
            .filter(e => (e.className||'').includes('bg-neutral-900') && e.getBoundingClientRect().width > 300)
            .map(e => { const r = e.getBoundingClientRect(); return {cy: r.top + r.height/2}; })""")
        print("visual lanes:", len(lanes), [round(l['cy']) for l in lanes])
        check("a spare visual lane exists (>=2 lanes for a 1-clip content)", len(lanes) >= 2)
        # drag V1 to the OTHER lane
        v1 = page.query_selector("[data-clip-id='V1']").bounding_box()
        v1cy = v1['y'] + v1['height'] / 2
        other = max(lanes, key=lambda l: abs(l['cy'] - v1cy))
        gx = v1['x'] + v1['width'] / 2
        page.mouse.move(gx, v1cy); page.mouse.down()
        for k in range(1, 11):
            page.mouse.move(gx, v1cy + (other['cy'] - v1cy) * k / 10); page.wait_for_timeout(30)
        page.mouse.up(); page.wait_for_timeout(1500)
        layer_after = v1_layer()
        print("V1 layer after move:", layer_after)
        check("single-lane clip CAN move to the spare lane (layer changed)", layer_after not in (0, None), f"layer={layer_after}")
        b.close()
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nLANE AUTOSPARE:", "ALL PASS" if ok else "FAILURES")
