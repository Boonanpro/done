"""Verify Stage 2: dragging the PiP/overlay box in the preview changes the clip's position.
Selects an overlay clip on the timeline, seeks to where it's active, then drags the box
overlay and confirms editSequence position changed (via the side-panel % readouts or the
box style). Read positions before/after a programmatic drag of the box element."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.auth_service import create_token_pair

ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
BASE = "http://127.0.0.1:3000"
tp = create_token_pair(user_id="2582a188-ff24-4a4f-b989-6063034d90b2", email="0aw325171@gmail.com")
contents = json.loads((Path("uploads/production-assets") / ROOM / "contents.json").read_text(encoding="utf-8"))
ct = next(c for c in contents if c["id"].startswith("8a429e2b"))
cid = ct["id"]
# find an overlay clip + a time where it's active
ov = next(c for t in ct["timeline"]["sequence"]["tracks"] if t["type"] == "overlay" for c in t["clips"])
mid = round((ov["timeline_start"] + ov["timeline_end"]) / 2, 1)
dur = ct["timeline"]["sequence"].get("duration", 152)
print(f"[pip] overlay {ov['id']} active around {mid}s, pos={ov.get('position')}")
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

    # switch to select tool so the annotation layer is transparent and the box is grabbable
    sel = page.query_selector("button[title*='選択'], button:has(svg.lucide-mouse-pointer-2)")
    # fallback: first tool button
    if sel:
        sel.click(); page.wait_for_timeout(300)

    # seek to mid via lane click
    def seek_to(frac):
        spot = page.evaluate("""(frac) => {
          const lanes = Array.from(document.querySelectorAll('div')).filter(e => {
            const c=(e.className||'').toString();
            return c.includes('bg-neutral-900') && e.getBoundingClientRect().width > 300; });
          const lane = lanes[lanes.length-1]; if(!lane) return null;
          const r = lane.getBoundingClientRect(); return {x: r.left + r.width*frac, y: r.top + r.height/2};
        }""", frac)
        if spot:
            page.mouse.click(spot["x"], spot["y"]); page.wait_for_timeout(1200)
    seek_to(mid / dur)

    # select the overlay clip block on the timeline by its title
    handle = page.query_selector(f"[title*='{ov['id']}']")
    # the clip bars may not carry the id; instead click an overlay lane bar near the playhead.
    # Simpler: the box only appears when the overlay clip is selected. Try clicking the
    # overlay timeline bar (amber/overlay-colored). Fallback: set selection via any clip bar.
    # We detect the box by its border-sky-400 + cursor-move.
    def box_rect():
        return page.evaluate("""() => {
          const b = document.querySelector('div.cursor-move.border-sky-400');
          if (!b) return null;
          const s = b.style;
          return { left: s.left, top: s.top, width: s.width, height: s.height,
                   r: b.getBoundingClientRect() };
        }""")

    # Need to select the overlay clip. Click overlay bars (look for clip bars in lanes).
    # Try clicking each clip bar until the box appears.
    bars = page.query_selector_all("div[style*='left:'][style*='width:']")
    appeared = False
    for bar in bars:
        try:
            bb = bar.bounding_box()
            if not bb or bb["width"] < 8:
                continue
            page.mouse.click(bb["x"] + min(bb["width"]/2, 20), bb["y"] + bb["height"]/2)
            page.wait_for_timeout(250)
            if box_rect():
                appeared = True
                break
        except Exception:
            continue
    print(f"[pip] selection box appeared: {appeared}")
    before = box_rect()
    if before:
        print(f"[pip] box before: left={before['left']} top={before['top']} w={before['width']} h={before['height']}")
        r = before["r"]
        # drag the box body by +60px x, +40px y
        page.mouse.move(r["x"] + r["width"]/2, r["y"] + r["height"]/2)
        page.mouse.down()
        for k in (1, 2, 3):
            page.mouse.move(r["x"] + r["width"]/2 + 20*k, r["y"] + r["height"]/2 + 14*k)
            page.wait_for_timeout(100)
        page.mouse.up()
        page.wait_for_timeout(500)
        after = box_rect()
        print(f"[pip] box after:  left={after['left']} top={after['top']} w={after['width']} h={after['height']}")
        moved = before["left"] != after["left"] or before["top"] != after["top"]
        print(f"[pip] RESULT: {'PASS — dragging the box moved the PiP position' if moved else 'FAIL — position did not change'}")
    else:
        print("[pip] RESULT: CHECK — could not get the box (selection/seek may have missed)")
    b.close()
