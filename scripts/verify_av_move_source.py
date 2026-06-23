"""A/V move bug: moving a VIDEO clip horizontally must shift the linked AUDIO partner's TIMELINE
position but keep its SOURCE range unchanged. (Before the fix both timeline+source shifted by the
same delta and cancelled out, so the audio looked moved but played the same content at the same
moment = 'voice doesn't follow the video'.)"""
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

# V and A linked, placed mid-timeline so there's room to drag both ways; source 10-13.
seq = {"format": "9:16", "duration": 20.0, "tracks": [
    {"id": "tv", "type": "video", "clips": [{"id": "V1", "asset_id": MAIN, "track": "video", "layer": 0,
        "timeline_start": 6, "timeline_end": 9, "source_start": 10, "source_end": 13,
        "composition": "fullscreen", "link_id": "L1", "role": "main"}]},
    {"id": "ta", "type": "audio", "clips": [{"id": "A1", "asset_id": MAIN, "track": "audio", "layer": 0,
        "timeline_start": 6, "timeline_end": 9, "source_start": 10, "source_end": 13,
        "role": "dialogue", "link_id": "L1"}]}]}

content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "AV MOVE TEST", "format": "9:16", "asset_ids": [MAIN],
     "timeline": {"format": "9:16", "source_asset_ids": [MAIN], "annotations": []}})).json()
cid = content["id"]
P._update_content(ROOM, cid, {"timeline": {"sequence": seq, "annotations": []}})
print("throwaway content:", cid[:8])

def clip(cid_, clip_id):
    ct = next(c for c in requests.get(f"{APIB}/contents?room_id={ROOM}", headers=H, cookies=C, timeout=30).json() if c["id"] == cid_)
    for t in (ct.get("timeline") or {}).get("sequence", {}).get("tracks", []):
        for c in t.get("clips", []):
            if c["id"] == clip_id:
                return c
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
        a_before = clip(cid, "A1")
        print("A1 before: tl", a_before["timeline_start"], "src", a_before["source_start"])
        # drag V1 to the RIGHT (grab its middle, move +120px horizontally)
        el = page.query_selector("[data-clip-id='V1']").bounding_box()
        cy = el['y'] + el['height']/2; cx = el['x'] + el['width']/2
        page.mouse.move(cx, cy); page.mouse.down()
        for k in range(1, 11):
            page.mouse.move(cx + 120 * k/10, cy); page.wait_for_timeout(25)
        page.mouse.up(); page.wait_for_timeout(1600)
        b.close()

    v = clip(cid, "V1"); a = clip(cid, "A1")
    print("after move: V1 tl", v["timeline_start"], "src", v["source_start"], "| A1 tl", a["timeline_start"], "src", a["source_start"])
    check("video moved right (timeline_start increased)", v["timeline_start"] > 6.2, f"V tl={v['timeline_start']}")
    check("audio partner FOLLOWED the move (timeline_start increased ~same)",
          abs(a["timeline_start"] - v["timeline_start"]) < 0.1, f"A tl={a['timeline_start']} V tl={v['timeline_start']}")
    check("audio SOURCE unchanged (still 10)",
          abs(a["source_start"] - 10) < 0.05, f"A src={a['source_start']} (was 10)")
    check("video SOURCE unchanged (still 10)", abs(v["source_start"] - 10) < 0.05, f"V src={v['source_start']}")
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nA/V MOVE:", "ALL PASS" if ok else "FAILURES")
