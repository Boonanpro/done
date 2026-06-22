"""Slice 4: verify multi-clip block move. Isolated throwaway content with 3 spaced video clips
A(0-2) B(4-6) C(8-10). Shift-select A+B, then drag B as a block. Asserts from the persisted
sequence that A and B moved by the SAME delta (relative spacing preserved), C is untouched, and
each clip's duration is unchanged. Throwaway content is deleted afterward — real content never
touched."""
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

def vclip(i, s, e):
    return {"id": f"bm_{i}", "asset_id": MAIN, "track": "video", "layer": 0,
            "timeline_start": s, "timeline_end": e, "source_start": s, "source_end": e,
            "composition": "fullscreen", "label": f"clip{i}"}

seq = {"format": "9:16", "duration": 10.0, "tracks": [
    {"type": "video", "clips": [vclip("A", 0, 2), vclip("B", 4, 6), vclip("C", 8, 10)]}]}

content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "BLOCKMOVE TEST (throwaway)", "format": "9:16", "asset_ids": [MAIN],
     "timeline": {"format": "9:16", "source_asset_ids": [MAIN], "annotations": []}})).json()
cid = content["id"]
P._update_content(ROOM, cid, {"timeline": {"sequence": seq, "annotations": []}})
print("throwaway content:", cid[:8])

def read_clips():
    ct = next(c for c in requests.get(f"{APIB}/contents?room_id={ROOM}", headers=H, cookies=C, timeout=30).json() if c["id"] == cid)
    s = (ct.get("timeline") or {}).get("sequence") or {}
    out = {}
    for t in s.get("tracks", []):
        for c in t.get("clips", []):
            out[c["id"]] = c
    return out

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

        # the 3 video bars, left-to-right = A, B, C; click their CENTER (the move handle)
        def bars():
            return page.evaluate("""() => Array.from(document.querySelectorAll('div[style*="left:"][style*="width:"]'))
                .map(b => { const r=b.getBoundingClientRect(); return {cx:r.left+r.width/2, cy:r.top+r.height/2, w:r.width, left:parseFloat(b.style.left)||0}; })
                .filter(b => b.w > 4).sort((a,c)=>a.left-c.left)""")
        bb = bars()
        print("bars:", len(bb))
        A, Bx, Cx = bb[0], bb[1], bb[2]

        # select A, then shift-select B
        page.mouse.click(A["cx"], A["cy"]); page.wait_for_timeout(250)
        page.keyboard.down("Shift"); page.mouse.click(Bx["cx"], Bx["cy"]); page.keyboard.up("Shift")
        page.wait_for_timeout(300)

        # drag the block by grabbing B and moving right ~140px
        page.mouse.move(Bx["cx"], Bx["cy"]); page.mouse.down()
        steps = 10
        for k in range(1, steps + 1):
            page.mouse.move(Bx["cx"] + 140 * k / steps, Bx["cy"]); page.wait_for_timeout(20)
        page.mouse.up()
        page.wait_for_timeout(1500)
        b.close()

    cl = read_clips()
    a, bx, cx = cl.get("bm_A"), cl.get("bm_B"), cl.get("bm_C")
    print("A", (a or {}).get("timeline_start"), (a or {}).get("timeline_end"),
          "| B", (bx or {}).get("timeline_start"), (bx or {}).get("timeline_end"),
          "| C", (cx or {}).get("timeline_start"), (cx or {}).get("timeline_end"))
    dA = a["timeline_start"] - 0.0
    dB = bx["timeline_start"] - 4.0
    check("A moved right", dA > 0.1, f"dA={dA:.2f}")
    check("B moved by the SAME delta as A", abs(dA - dB) < 0.06, f"dA={dA:.2f} dB={dB:.2f}")
    check("A-B relative spacing preserved (4s)", abs((bx["timeline_start"] - a["timeline_start"]) - 4.0) < 0.06)
    check("A duration preserved (2s)", abs((a["timeline_end"] - a["timeline_start"]) - 2.0) < 0.06)
    check("B duration preserved (2s)", abs((bx["timeline_end"] - bx["timeline_start"]) - 2.0) < 0.06)
    check("C untouched (8-10)", abs(cx["timeline_start"] - 8.0) < 0.06 and abs(cx["timeline_end"] - 10.0) < 0.06)
    check("source ranges unchanged on move (A src 0-2)", abs(a.get("source_start", 0) - 0) < 0.06 and abs(a.get("source_end", 0) - 2) < 0.06)
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nBLOCK MOVE:", "ALL PASS" if ok else "FAILURES")
