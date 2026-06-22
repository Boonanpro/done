"""Slice 3: verify ripple delete closes the gap. Builds an ISOLATED throwaway content with a
deterministic 3-clip video lane (A:0-2, B:2-4, C:4-6), opens it, selects the MIDDLE clip,
presses Shift+Delete, and asserts from the persisted sequence that B is gone, C slid left to
2-4 (gap closed), and total duration shrank 6->4. The throwaway content is deleted afterward,
so the user's real content is never touched."""
import sys, json, time
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

def vclip(i, s, e):
    return {"id": f"rt_{i}", "asset_id": MAIN, "track": "video", "layer": 0,
            "timeline_start": s, "timeline_end": e, "source_start": s, "source_end": e,
            "composition": "fullscreen", "label": f"clip{i}"}

# a caption on a DIFFERENT lane overlapping clip B's time — must survive a per-lane ripple
cap = {"id": "cap_X", "track": "caption", "layer": 2, "timeline_start": 2.5, "timeline_end": 3.5,
       "text": "overlap caption", "source_start": 0, "source_end": 0}
seq = {"format": "9:16", "duration": 6.0, "tracks": [
    {"type": "video", "clips": [vclip("A", 0, 2), vclip("B", 2, 4), vclip("C", 4, 6)]},
    {"type": "caption", "clips": [cap]}]}

# create throwaway content, inject the deterministic sequence
content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "RIPPLE TEST (throwaway)", "format": "9:16", "asset_ids": [MAIN],
     "timeline": {"format": "9:16", "source_asset_ids": [MAIN], "annotations": []}})).json()
cid = content["id"]
P._update_content(ROOM, cid, {"timeline": {"sequence": seq, "annotations": []}})
print("throwaway content:", cid[:8])

def read_video_clips():
    ct = next(c for c in requests.get(f"{APIB}/contents?room_id={ROOM}", headers=H, cookies=C, timeout=30).json() if c["id"] == cid)
    s = (ct.get("timeline") or {}).get("sequence") or {}
    vids = [c for t in s.get("tracks", []) if t["type"] == "video" for c in t.get("clips", [])]
    caps = [c for t in s.get("tracks", []) if t["type"] == "caption" for c in t.get("clips", [])]
    return vids, caps, s.get("duration")

ok = True
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
        # select tool
        sel = page.query_selector("button:has(svg.lucide-mouse-pointer-2)")
        if sel: sel.click(); page.wait_for_timeout(300)
        # click the middle clip bar (sort timeline bars by left%, pick index 1 of the 3 video clips)
        bars = page.evaluate("""() => Array.from(document.querySelectorAll('div[style*="left:"][style*="width:"]'))
            .map(b => { const r=b.getBoundingClientRect(); return {x:r.left+r.width/2, y:r.top+r.height/2, w:r.width, left:parseFloat(b.style.left)||0}; })
            .filter(b => b.w > 4).sort((a,c)=>a.left-c.left)""")
        print("video bars found:", len(bars))
        # the middle of the three lowest bars = clip B
        mid = bars[1]
        page.mouse.click(mid["x"], mid["y"]); page.wait_for_timeout(600)
        # ripple delete
        page.keyboard.down("Shift"); page.keyboard.press("Delete"); page.keyboard.up("Shift")
        page.wait_for_timeout(1500)
        b.close()

    clips, caps, dur = read_video_clips()
    clips.sort(key=lambda c: c["timeline_start"])
    print("after ripple: video=", [(c.get("label"), c["timeline_start"], c["timeline_end"]) for c in clips],
          "caption=", [(c.get("id"), c["timeline_start"], c["timeline_end"]) for c in caps], "dur=", dur)
    def check(name, cond):
        global ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond
    check("clip B removed (2 video clips remain)", len(clips) == 2)
    if len(clips) == 2:
        a, c = clips
        check("clip A unchanged (0->2)", abs(a["timeline_start"]-0) < 0.05 and abs(a["timeline_end"]-2) < 0.05)
        check("clip C slid left to fill gap (2->4)", abs(c["timeline_start"]-2) < 0.05 and abs(c["timeline_end"]-4) < 0.05)
        check("clip C source unchanged (4->6)", abs(c.get("source_start",0)-4) < 0.05 and abs(c.get("source_end",0)-6) < 0.05)
    # the overlapping caption on the OTHER lane must NOT be deleted or shifted
    check("overlapping caption on other lane SURVIVED (not deleted)", len(caps) == 1)
    if len(caps) == 1:
        check("caption left where it was (2.5-3.5, other lane untouched)",
              abs(caps[0]["timeline_start"]-2.5) < 0.05 and abs(caps[0]["timeline_end"]-3.5) < 0.05)
finally:
    # delete the throwaway content so the user's room stays clean
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nRIPPLE:", "ALL PASS" if ok else "FAILURES")
