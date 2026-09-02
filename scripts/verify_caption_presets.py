"""Telop preset picker: select a caption clip, click a preset chip, assert the style is applied
and persisted (the same CaptionStyle fields the .ass renderer honors, so preview == export)."""
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

seq = {"format": "9:16", "duration": 8.0, "tracks": [
    {"id": "tv", "type": "video", "clips": [{"id": "V1", "asset_id": MAIN, "track": "video", "layer": 0,
        "timeline_start": 0, "timeline_end": 8, "source_start": 0, "source_end": 8, "composition": "fullscreen", "role": "main"}]},
    {"id": "tc", "type": "caption", "clips": [
        {"id": "CAP1", "track": "caption", "layer": 0, "timeline_start": 1, "timeline_end": 4, "text": "テロップ1"},
        {"id": "CAP2", "track": "caption", "layer": 0, "timeline_start": 4.5, "timeline_end": 7, "text": "テロップ2"}]}]}

content = requests.post(f"{APIB}/contents", headers=H, cookies=C, timeout=30, data=json.dumps(
    {"room_id": ROOM, "title": "CAPTION PRESET", "format": "9:16", "asset_ids": [MAIN],
     "timeline": {"format": "9:16", "source_asset_ids": [MAIN], "annotations": []}})).json()
cid = content["id"]
P._update_content(ROOM, cid, {"timeline": {"sequence": seq, "annotations": []}})
print("throwaway content:", cid[:8])

def caption_clips():
    ct = next(c for c in requests.get(f"{APIB}/contents?room_id={ROOM}", headers=H, cookies=C, timeout=30).json() if c["id"] == cid)
    return {c["id"]: c for t in (ct.get("timeline") or {}).get("sequence", {}).get("tracks", []) if t["type"] == "caption" for c in t.get("clips", [])}

ok = True
def check(name, cond, detail=""):
    global ok; print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}"); ok = ok and cond

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
        page.wait_for_timeout(7000)
        # select caption clip CAP1
        cap = page.query_selector("[data-clip-id='CAP1']")
        check("caption clip CAP1 visible in timeline", cap is not None)
        if cap:
            cap.click(); page.wait_for_timeout(600)
        # preset chips present?
        chips = page.query_selector_all("button[title='赤強調'], button[title='黄ポップ'], button[title='シアン']")
        check("preset chips rendered in design panel", len(chips) >= 1, f"found {len(chips)} known chips")
        # click 赤強調
        red = page.query_selector("button[title='赤強調']")
        check("赤強調 preset chip exists", red is not None)
        if red:
            red.click(); page.wait_for_timeout(900)
        # apply-to-all button
        allbtn = page.query_selector("button:has-text('この見た目を全テロップに適用')")
        check("apply-to-all button exists", allbtn is not None)
        if allbtn:
            allbtn.click()
        page.wait_for_timeout(2400)  # past the 1200ms autosave debounce before closing
        b.close()

    cc = caption_clips()
    c1 = cc.get("CAP1"); c2 = cc.get("CAP2")
    print("CAP1 style:", (c1 or {}).get("style")); print("CAP2 style:", (c2 or {}).get("style"))
    s1 = (c1 or {}).get("style") or {}
    check("CAP1 got 赤強調 color #ff3b30", str(s1.get("color", "")).lower() == "#ff3b30", f"color={s1.get('color')}")
    check("CAP1 got white outline #ffffff", str(s1.get("outlineColor", "")).lower() == "#ffffff", f"outline={s1.get('outlineColor')}")
    check("CAP1 got fontSize 1.1", abs(float(s1.get("fontSize") or 0) - 1.1) < 0.01, f"fontSize={s1.get('fontSize')}")
    s2 = (c2 or {}).get("style") or {}
    check("CAP2 got SAME style via apply-to-all (color)", str(s2.get("color", "")).lower() == "#ff3b30", f"CAP2 color={s2.get('color')}")
finally:
    cpath = P._room_dir(ROOM) / "contents.json"
    data = json.loads(cpath.read_text(encoding="utf-8"))
    data = [c for c in data if c["id"] != cid]
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[cleanup] throwaway content removed")

print("\nCAPTION PRESETS:", "ALL PASS" if ok else "FAILURES")
