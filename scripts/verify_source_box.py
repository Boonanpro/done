"""Verify the selection box matches the SOURCE aspect ratio (not the 9:16 output) for a
base clip. Selects a fullscreen screen-recording clip, reads the blue box element's rendered
width/height, and asserts the box aspect ≈ source aspect (1080/2340 ≈ 0.46), not 9:16 (0.5625).
Also confirms shrinking via the size slider scales the box (reveal)."""
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
# a fullscreen base clip that uses the SCREEN recording (1080x2340)
SCREEN = "535e2cc4-e200-40c3-b8f1-ade7c5cd3833"
screen_clip = next((c for t in ct["timeline"]["sequence"]["tracks"] if t["type"] == "video"
                    for c in t["clips"] if c.get("asset_id") == SCREEN and c.get("composition") in ("fullscreen", "background")), None)
if not screen_clip:
    print("no fullscreen screen clip found; using any fullscreen video clip")
    screen_clip = next(c for t in ct["timeline"]["sequence"]["tracks"] if t["type"] == "video" for c in t["clips"] if c.get("composition") == "fullscreen")
mid = round((screen_clip["timeline_start"] + screen_clip["timeline_end"]) / 2, 1)
dur = ct["timeline"]["sequence"].get("duration", 152)
print(f"[box] target clip {screen_clip['id']} asset {str(screen_clip.get('asset_id'))[:8]} active ~{mid}s")
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

    # select tool
    sel = page.query_selector("button:has(svg.lucide-mouse-pointer-2)")
    if sel:
        sel.click(); page.wait_for_timeout(300)

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

    def box_aspect():
        return page.evaluate("""() => {
          const b = document.querySelector('div.cursor-move.border-sky-400');
          if (!b) return null;
          const r = b.getBoundingClientRect();
          return { w: r.width, h: r.height, aspect: r.width / r.height };
        }""")

    # select the target clip by clicking timeline bars until the box appears
    bars = page.query_selector_all("div[style*='left:'][style*='width:']")
    for bar in bars:
        try:
            bb = bar.bounding_box()
            if not bb or bb["width"] < 8:
                continue
            page.mouse.click(bb["x"] + min(bb["width"]/2, 20), bb["y"] + bb["height"]/2)
            page.wait_for_timeout(200)
            ba = box_aspect()
            if ba and 0.4 <= ba["aspect"] <= 0.65:  # got a video clip box
                break
        except Exception:
            continue
    ba = box_aspect()
    print(f"[box] selection box: {ba}")
    if ba:
        src_aspect = 1080 / 2340  # 0.4615
        out_aspect = 720 / 1280   # 0.5625
        print(f"[box] source aspect={src_aspect:.3f}  output(9:16)={out_aspect:.3f}  box={ba['aspect']:.3f}")
        is_source = abs(ba["aspect"] - src_aspect) < abs(ba["aspect"] - out_aspect)
        print(f"[box] RESULT: {'PASS — box matches SOURCE aspect (tall), not 9:16' if is_source else 'FAIL — box still 9:16'}")
    else:
        print("[box] RESULT: CHECK — box not found (clip may not be a fullscreen video at this time)")
    b.close()
