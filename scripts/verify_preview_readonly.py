"""READ-ONLY verification of the cleaned-up timeline preview (no edits/deletes).
Confirms: page loads w/o errors, canvas composites, scrub changes the frame,
playback advances smoothly (no rewind), and the legacy HTML caption overlay is gone
(captions now only on the canvas). Never mutates the user's content."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.auth_service import create_token_pair

USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"
EMAIL = "0aw325171@gmail.com"
ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
CONTENT = "68ab4fe4-6f96-4f72-b085-f818fae83a8d"
BASE = "http://127.0.0.1:3000"
URL = f"{BASE}/production-workspace?room_id={ROOM}&content_id={CONTENT}"
tp = create_token_pair(user_id=USER_ID, email=EMAIL)
TMP = r"C:\Users\Owner\AppData\Local\Temp"

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    try:
        b = p.chromium.launch(headless=True, channel="chrome", args=["--autoplay-policy=no-user-gesture-required"])
    except Exception:
        b = p.chromium.launch(headless=True, channel="msedge", args=["--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context(viewport={"width": 1400, "height": 900})
    ctx.add_cookies([{"name": "done_access_token", "value": tp.access_token, "url": BASE},
                     {"name": "done_refresh_token", "value": tp.refresh_token, "url": BASE}])
    ctx.add_init_script(f"window.localStorage.setItem('done-token', {tp.access_token!r});")
    page = ctx.new_page()
    errs = []
    page.on("console", lambda m: errs.append(m.text[:160]) if m.type == "error" else None)
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(9000)

    print("[ro] canvas present:", bool(page.query_selector("canvas")))
    # Legacy HTML caption overlay had bg-black/70 + bottom-8; it should be GONE now.
    html_caption_overlays = page.evaluate("""() => Array.from(document.querySelectorAll('div'))
        .filter(e => { const c=(e.className||'').toString(); return c.includes('bottom-8') && c.includes('bg-black/70'); }).length""")
    print(f"[ro] legacy HTML caption overlays (should be 0): {html_caption_overlays}")
    cap_handles = page.evaluate("""() => Array.from(document.querySelectorAll('[title]'))
        .filter(e=>(e.getAttribute('title')||'').startsWith('テロップ')).length""")
    print(f"[ro] caption clip handles on timeline (data intact -> 3): {cap_handles}")

    def lane_click(frac, label):
        spot = page.evaluate("""(frac) => {
          const lanes = Array.from(document.querySelectorAll('div')).filter(e => {
            const c=(e.className||'').toString();
            return c.includes('bg-neutral-900') && e.getBoundingClientRect().width > 300; });
          const lane = lanes[lanes.length-1]; if(!lane) return null;
          const r = lane.getBoundingClientRect(); return {x: r.left + r.width*frac, y: r.top + r.height/2};
        }""", frac)
        if spot:
            page.mouse.click(spot["x"], spot["y"]); page.wait_for_timeout(1500)
        cv = page.query_selector("canvas")
        if cv: cv.screenshot(path=fr"{TMP}\ro_{label}.png")
        print(f"[ro] scrub frac={frac} -> ro_{label}.png")

    lane_click(0.05, "intro")
    lane_click(0.45, "op")
    lane_click(0.90, "promise")  # the restored 3rd caption should appear here

    # PLAY smoothness (read-only): sample video.currentTime, count backward jumps
    play = page.query_selector('[title^="再生"]')
    if play:
        play.click()
        samples = []
        for _ in range(6):
            page.wait_for_timeout(350)
            samples.append(page.evaluate("() => { const v=document.querySelectorAll('video')[0]; return v? Math.round(v.currentTime*100)/100 : null; }"))
        backs = sum(1 for a, b in zip(samples, samples[1:]) if a is not None and b is not None and b < a - 0.05)
        adv = (samples[-1] or 0) - (samples[0] or 0)
        print(f"[ro] PLAY samples={samples} advanced={adv:.2f}s over ~2.1s backward_jumps={backs}")
        pause = page.query_selector('[title^="一時停止"]')
        if pause: pause.click()

    print("[ro] console errors:", [e for e in errs[:8]])
    b.close()
print("[ro] done")
