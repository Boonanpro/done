"""A/V collision avoidance: when a moved video clip's linked audio lands on an EXISTING audio
clip, the moved audio must bump to a new lane (auto-created) and NOT delete the existing clip.
Content: V+A (tl 2-5) linked, plus a standalone audio clip B (tl 6.5-9.5, layer 0). Move V right
so A overlaps B; assert B still exists and A is on a different (lower) lane."""
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

seq = {"format": "9:16", "duration": 16.0, "tracks": [
    {"id": "tv", "type": "video", "clips": [{"id": "V1", "asset_id": MAIN, "track": "video", "layer": 0,
        "timeline_start": 2, "timeline_end": 5, "source_start": 10, "source_end": 13,
        "composition": "fullscreen", "link_id": "L1", "role": "main"}]},
    {"id": "ta", "type": "audio", "clips": [
        {"id": "A1", "asset_id": MAIN, "track": "audio", "layer": 0, "timeline_start": 2, "timeline_end": 5,
         "source_start": 10, "source_end": 13, "role": "dialogue", "link_id": "L1"},
        {"id": "B1", "asset_id": MAIN, "track": "audio", "layer": 0, "timeline_start": 6.5, "timeline_end": 9.5,
         "source_start": 50, "source_end": 53, "role": "dialogue"}]}]}

content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "AV COLLISION", "format": "9:16", "asset_ids": [MAIN],
     "timeline": {"format": "9:16", "source_asset_ids": [MAIN], "annotations": []}})).json()
cid = content["id"]
P._update_content(ROOM, cid, {"timeline": {"sequence": seq, "annotations": []}})
print("throwaway content:", cid[:8])

def audio_clips():
    ct = next(c for c in requests.get(f"{APIB}/contents?room_id={ROOM}", headers=H, cookies=C, timeout=30).json() if c["id"] == cid)
    return {c["id"]: c for t in (ct.get("timeline") or {}).get("sequence", {}).get("tracks", []) if t["type"] == "audio" for c in t.get("clips", [])}

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
        # drag V1 right far enough that A1 (now at V1's time) overlaps B1 (6.5-9.5)
        el = page.query_selector("[data-clip-id='V1']").bounding_box()
        cy = el['y'] + el['height']/2; cx = el['x'] + el['width']/2
        page.mouse.move(cx, cy); page.mouse.down()
        for k in range(1, 13):
            page.mouse.move(cx + 200 * k/12, cy); page.wait_for_timeout(25)
        page.mouse.up(); page.wait_for_timeout(1600)
        b.close()

    ac = audio_clips()
    a, b1 = ac.get("A1"), ac.get("B1")
    print("audio clips:", {k: (round(v["timeline_start"],2), round(v["timeline_end"],2), "layer", v.get("layer"), "src", round(v.get("source_start",0),1)) for k, v in ac.items()})
    check("existing audio clip B1 PRESERVED (not deleted)", b1 is not None)
    check("moved audio A1 still present", a is not None)
    if a and b1:
        a_over_b = a["timeline_end"] > b1["timeline_start"] + 0.05 and a["timeline_start"] < b1["timeline_end"] - 0.05
        check("A1 now overlaps B1 in time (the collision case)", a_over_b,
              f"A {a['timeline_start']}-{a['timeline_end']} B {b1['timeline_start']}-{b1['timeline_end']}")
        check("A1 bumped to a DIFFERENT lane than B1 (not overwriting)", (a.get("layer") or 0) != (b1.get("layer") or 0),
              f"A.layer={a.get('layer')} B.layer={b1.get('layer')}")
        check("A1 source stayed aligned with video (10)", abs(a.get("source_start", 0) - 10) < 0.05, f"A.src={a.get('source_start')}")
        check("B1 source untouched (50)", abs(b1.get("source_start", 0) - 50) < 0.05, f"B.src={b1.get('source_start')}")
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nA/V COLLISION:", "ALL PASS" if ok else "FAILURES")
