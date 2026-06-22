"""Slice 4 follow-up: block move must overwrite (trim/delete/split) same-lane neighbours like a
single-clip move. Isolated content: video A(0-2) B(2-4) selected + neighbour N(4.5-7). Shift-
select A+B, drag right; assert A&B moved by the same delta, N got trimmed/deleted so NO two
clips on the lane overlap. Throwaway content deleted afterward."""
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
    return {"id": f"o_{i}", "asset_id": MAIN, "track": "video", "layer": 0,
            "timeline_start": s, "timeline_end": e, "source_start": s, "source_end": e,
            "composition": "fullscreen", "label": f"clip{i}"}

seq = {"format": "9:16", "duration": 7.0, "tracks": [
    {"id": "tk_v", "type": "video", "clips": [vclip("A", 0, 2), vclip("B", 2, 4), vclip("N", 4.5, 7)]}]}

content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "BLOCKOVR TEST (throwaway)", "format": "9:16", "asset_ids": [MAIN],
     "timeline": {"format": "9:16", "source_asset_ids": [MAIN], "annotations": []}})).json()
cid = content["id"]
P._update_content(ROOM, cid, {"timeline": {"sequence": seq, "annotations": []}})
print("throwaway content:", cid[:8])

def read_clips():
    ct = next(c for c in requests.get(f"{APIB}/contents?room_id={ROOM}", headers=H, cookies=C, timeout=30).json() if c["id"] == cid)
    s = (ct.get("timeline") or {}).get("sequence") or {}
    out = {}
    vids = []
    for t in s.get("tracks", []):
        if t["type"] != "video":
            continue
        for c in t.get("clips", []):
            out[c["id"]] = c
            vids.append(c)
    return out, vids

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
        bb = page.evaluate("""() => Array.from(document.querySelectorAll('div[style*="left:"][style*="width:"]'))
            .map(b => { const r=b.getBoundingClientRect(); return {cx:r.left+r.width/2, cy:r.top+r.height/2, w:r.width, left:parseFloat(b.style.left)||0}; })
            .filter(b => b.w > 4).sort((a,c)=>a.left-c.left)""")
        A, Bx = bb[0], bb[1]
        page.mouse.click(A["cx"], A["cy"]); page.wait_for_timeout(250)
        page.keyboard.down("Shift"); page.mouse.click(Bx["cx"], Bx["cy"]); page.keyboard.up("Shift"); page.wait_for_timeout(300)
        page.mouse.move(Bx["cx"], Bx["cy"]); page.mouse.down()
        for k in range(1, 11):
            page.mouse.move(Bx["cx"] + 130 * k / 10, Bx["cy"]); page.wait_for_timeout(20)
        page.mouse.up()
        page.wait_for_timeout(1600)
        b.close()

    cl, vids = read_clips()
    a, bx = cl.get("o_A"), cl.get("o_B")
    print("after:", [(c.get("id"), round(c["timeline_start"], 2), round(c["timeline_end"], 2)) for c in sorted(vids, key=lambda c: c["timeline_start"])])
    dA = a["timeline_start"] - 0.0
    dB = bx["timeline_start"] - 2.0
    check("A moved right", dA > 0.1, f"dA={dA:.2f}")
    check("B moved by the SAME delta as A", abs(dA - dB) < 0.06, f"dA={dA:.2f} dB={dB:.2f}")
    # overwrite invariant: no two video clips overlap on the lane
    sv = sorted(vids, key=lambda c: c["timeline_start"])
    overlaps = [(sv[i]["id"], sv[i+1]["id"]) for i in range(len(sv)-1) if sv[i]["timeline_end"] > sv[i+1]["timeline_start"] + 0.05]
    check("no overlapping clips after block move (neighbour trimmed/deleted)", not overlaps, str(overlaps))
    # N specifically must have been affected (trimmed start >= B end, or deleted)
    n = cl.get("o_N")
    if n is not None:
        check("neighbour N trimmed (no overlap with B)", n["timeline_start"] >= bx["timeline_end"] - 0.06,
              f"N.start={n['timeline_start']:.2f} B.end={bx['timeline_end']:.2f}")
    else:
        check("neighbour N consumed (deleted)", True)
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nBLOCK MOVE OVERWRITE:", "ALL PASS" if ok else "FAILURES")
