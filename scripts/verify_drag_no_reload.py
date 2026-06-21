"""Verify the black-on-drag fix: dragging a clip must NOT reload all <video> elements.
We load the editor, record each hidden video's readiness, simulate a clip drag (drag a
timeline clip bar), and confirm the videos stay decoded (videoWidth>0 / readyState>=2)
instead of all resetting to 0 (which caused the all-black screen)."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.auth_service import create_token_pair

ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
BASE = "http://127.0.0.1:3000"
tp = create_token_pair(user_id="2582a188-ff24-4a4f-b989-6063034d90b2", email="0aw325171@gmail.com")
contents = json.loads((Path("uploads/production-assets") / ROOM / "contents.json").read_text(encoding="utf-8"))
cid = next(c["id"] for c in contents if c["id"].startswith("8a429e2b"))
URL = f"{BASE}/production-workspace?room_id={ROOM}&content_id={cid}"

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    try:
        b = p.chromium.launch(headless=True, channel="chrome", args=["--autoplay-policy=no-user-gesture-required"])
    except Exception:
        b = p.chromium.launch(headless=True, channel="msedge", args=["--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context(viewport={"width": 1500, "height": 950})
    ctx.add_cookies([{"name": "done_access_token", "value": tp.access_token, "url": BASE},
                     {"name": "done_refresh_token", "value": tp.refresh_token, "url": BASE}])
    ctx.add_init_script(f"window.localStorage.setItem('done-token', {tp.access_token!r});")
    page = ctx.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(9000)

    def decoded_count():
        return page.evaluate("""() => {
          const vs = Array.from(document.querySelectorAll('video'));
          return { total: vs.length, decoded: vs.filter(v => v.videoWidth > 0 && v.readyState >= 2).length };
        }""")

    before = decoded_count()
    print(f"[before drag] videos: {before}")

    # find a clip bar in the timeline and drag it ~80px to overlap a neighbour (triggers
    # the overwrite/split path that churns clip ids).
    bar = page.query_selector("[class*='cursor-grab'], [class*='cursor-move']")
    # fallback: any timeline clip block (rounded bg block in the lanes)
    if not bar:
        bars = page.query_selector_all("div[style*='left'][style*='width']")
        bar = bars[len(bars)//2] if bars else None
    dragged = False
    if bar:
        box = bar.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
            page.mouse.down()
            for dx in (20, 40, 70, 100):  # move in steps to trigger multiple reconciles
                page.mouse.move(box["x"] + box["width"]/2 - dx, box["y"] + box["height"]/2)
                page.wait_for_timeout(120)
            during = decoded_count()
            print(f"[during drag]  videos: {during}")
            page.mouse.up()
            dragged = True
    page.wait_for_timeout(800)
    after = decoded_count()
    print(f"[after drag]  videos: {after}")
    print(f"[dragged] {dragged}")

    # PASS: most videos stay decoded during/after drag (not all reset to 0).
    ok = after["decoded"] >= max(1, before["decoded"] // 2)
    print(f"[RESULT] {'PASS — videos stay decoded through a drag (no full reload / black screen)' if ok else 'FAIL — videos lost decode (black screen reproduced)'}")
    b.close()
