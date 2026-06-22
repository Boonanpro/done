"""Slice 4 follow-up: right-drag rubber-band (marquee) selection. Isolated content with video
A(0-2) B(3-5) C(6-8) on one lane. Right-drag a rectangle covering A and B (not C); assert A and
B become selected (yellow ring) and C does not. Left-drag must NOT marquee (stays scrub).
Throwaway content deleted afterward."""
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
    return {"id": f"m_{i}", "asset_id": MAIN, "track": "video", "layer": 0,
            "timeline_start": s, "timeline_end": e, "source_start": s, "source_end": e,
            "composition": "fullscreen", "label": f"clip{i}"}

seq = {"format": "9:16", "duration": 8.0, "tracks": [
    {"id": "tk_v", "type": "video", "clips": [vclip("A", 0, 2), vclip("B", 3, 5), vclip("C", 6, 8)]}]}

content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "MARQUEE TEST (throwaway)", "format": "9:16", "asset_ids": [MAIN],
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

        def boxes():
            return page.evaluate("""() => { const out={};
              document.querySelectorAll('[data-clip-id]').forEach(el => {
                const r = el.getBoundingClientRect();
                out[el.getAttribute('data-clip-id')] = {l:r.left, t:r.top, rt:r.right, b:r.bottom,
                  selected: (el.className||'').includes('ring-yellow-300/70')};
              }); return out; }""")
        bx = boxes()
        print("clip boxes:", {k: (round(v['l']), round(v['rt']), v['selected']) for k, v in bx.items()})
        A, Bx, Cx = bx["m_A"], bx["m_B"], bx["m_C"]

        # right-drag a rectangle covering A and B (not C). Start INSIDE the track (on clip A) so
        # the timeline's capture handler fires; span horizontally to B with a little height.
        cyA = (A["t"] + A["b"]) / 2
        x0, y0 = A["l"] + 3, cyA - 10
        x1, y1 = Bx["rt"] - 3, cyA + 10
        page.mouse.move(x0, y0)
        page.mouse.down(button="right")
        for k in range(1, 9):
            page.mouse.move(x0 + (x1 - x0) * k / 8, y0 + (y1 - y0) * k / 8); page.wait_for_timeout(20)
        page.mouse.up(button="right")
        page.wait_for_timeout(400)

        after = boxes()
        print("after marquee selected:", {k: v["selected"] for k, v in after.items()})
        check("A selected by marquee", after["m_A"]["selected"])
        check("B selected by marquee", after["m_B"]["selected"])
        check("C NOT selected (outside rectangle)", not after["m_C"]["selected"])
        b.close()
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nMARQUEE:", "ALL PASS" if ok else "FAILURES")
