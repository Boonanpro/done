"""Undo/redo for sequence edits. Isolated throwaway content with 3 clips A/B/C. Delete the
middle clip (2 clips), Ctrl+Z -> back to 3, Ctrl+Shift+Z -> 2 again. Verifies the unified
history covers clip edits (not just annotations). Throwaway content deleted afterward."""
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
    return {"id": f"u_{i}", "asset_id": MAIN, "track": "video", "layer": 0,
            "timeline_start": s, "timeline_end": e, "source_start": s, "source_end": e,
            "composition": "fullscreen", "label": f"clip{i}"}

seq = {"format": "9:16", "duration": 6.0, "tracks": [
    {"id": "tk_v", "type": "video", "clips": [vclip("A", 0, 2), vclip("B", 2, 4), vclip("C", 4, 6)]}]}

content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "UNDO TEST (throwaway)", "format": "9:16", "asset_ids": [MAIN],
     "timeline": {"format": "9:16", "source_asset_ids": [MAIN], "annotations": []}})).json()
cid = content["id"]
P._update_content(ROOM, cid, {"timeline": {"sequence": seq, "annotations": []}})
print("throwaway content:", cid[:8])

def nclips():
    ct = next(c for c in requests.get(f"{APIB}/contents?room_id={ROOM}", headers=H, cookies=C, timeout=30).json() if c["id"] == cid)
    s = (ct.get("timeline") or {}).get("sequence") or {}
    return sum(len(t.get("clips", [])) for t in s.get("tracks", []) if t["type"] == "video")

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

        def bars():
            return page.evaluate("""() => Array.from(document.querySelectorAll('div[style*="left:"][style*="width:"]'))
                .map(b => { const r=b.getBoundingClientRect(); return {cx:r.left+r.width/2, cy:r.top+r.height/2, w:r.width, left:parseFloat(b.style.left)||0}; })
                .filter(b => b.w > 4).sort((a,c)=>a.left-c.left)""")
        bb = bars()
        print("bars:", len(bb))
        # select middle clip, delete it (gap-leaving delete)
        def dom_bars():
            return page.evaluate("""() => Array.from(document.querySelectorAll('div[style*="left:"][style*="width:"]'))
                .filter(b => (parseFloat(b.style.width)||0) > 0).length""")
        page.mouse.click(bb[1]["cx"], bb[1]["cy"]); page.wait_for_timeout(300)
        page.keyboard.press("Delete"); page.wait_for_timeout(700)
        print("DOM bars after delete:", dom_bars())
        page.wait_for_timeout(900)  # let autosave persist
        n_after_del = nclips()
        check("delete removed a clip (3 -> 2)", n_after_del == 2, f"n={n_after_del}")

        # Ctrl+Z -> should restore to 3
        page.mouse.move(bb[1]["cx"], bb[1]["cy"] - 60)  # ensure window focus, off any input
        page.keyboard.press("Control+z")
        page.wait_for_timeout(500)
        print("DOM bars right after Ctrl+Z:", dom_bars())
        page.wait_for_timeout(1500)
        n_after_undo = nclips()
        check("Ctrl+Z restored the clip (2 -> 3)", n_after_undo == 3, f"n={n_after_undo}")

        # Ctrl+Shift+Z -> redo back to 2
        page.keyboard.press("Control+Shift+z")
        page.wait_for_timeout(500)
        print("DOM bars right after redo:", dom_bars())
        page.wait_for_timeout(1500)
        n_after_redo = nclips()
        check("Ctrl+Shift+Z re-applied the delete (3 -> 2)", n_after_redo == 2, f"n={n_after_redo}")
        b.close()
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nUNDO/REDO:", "ALL PASS" if ok else "FAILURES")
