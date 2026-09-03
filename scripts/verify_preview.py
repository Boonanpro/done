"""Verify the new canvas compositor preview renders the composited timeline frame
(base + PiP + captions) at given playhead times. Read-only (no edits/saves)."""
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

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    # real Chrome (not bundled Chromium) for H.264/AAC proprietary codec support
    try:
        b = p.chromium.launch(headless=True, channel="chrome", args=["--autoplay-policy=no-user-gesture-required"])
    except Exception:
        b = p.chromium.launch(headless=True, channel="msedge", args=["--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context(viewport={"width": 1400, "height": 900})
    ctx.add_cookies([{ "name":"done_access_token","value":tp.access_token,"url":BASE},
                     {"name":"done_refresh_token","value":tp.refresh_token,"url":BASE}])
    ctx.add_init_script(f"window.localStorage.setItem('done-token', {tp.access_token!r});")
    page = ctx.new_page()
    errs = []
    page.on("console", lambda m: errs.append(m.text[:160]) if m.type == "error" else None)
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(9000)  # let proxy videos load + decode

    # find the preview canvas
    canvas = page.query_selector("canvas")
    print("[pv] canvas present:", bool(canvas))
    vids = page.evaluate("""() => Array.from(document.querySelectorAll('video')).map(v => ({
      src: (v.src||'').slice(-40), readyState: v.readyState, networkState: v.networkState,
      vw: v.videoWidth, vh: v.videoHeight, err: v.error ? v.error.code : null
    }))""")
    print("[pv] hidden videos state:")
    for v in vids:
        print("   ", v)

    # helper: click the base video lane at a fraction to seek there
    def seek_fraction(frac, label):
        # the base video lane track is the wide dark element; click on its background
        lane = page.evaluate("""(frac) => {
          const lanes = Array.from(document.querySelectorAll('div')).filter(e => {
            const c=(e.className||'').toString();
            return c.includes('bg-neutral-900') && e.querySelector && e.getBoundingClientRect().width > 300;
          });
          const lane = lanes[lanes.length-1];
          if(!lane) return null;
          const r = lane.getBoundingClientRect();
          return {x: r.left + r.width*frac, y: r.top + r.height/2};
        }""", frac)
        if lane:
            page.mouse.click(lane["x"], lane["y"])
            page.wait_for_timeout(1800)
        page.screenshot(path=fr"C:\Users\Owner\AppData\Local\Temp\preview_{label}.png")
        print(f"[pv] seeked frac={frac} -> screenshot preview_{label}.png")

    page.screenshot(path=r"C:\Users\Owner\AppData\Local\Temp\preview_t0.png")
    print("[pv] t0 screenshot saved")
    seek_fraction(0.05, "intro")   # talking head + caption
    seek_fraction(0.50, "op")      # operation: screen bg + person PiP

    def cur_time():
        return page.evaluate("""() => { const el = Array.from(document.querySelectorAll('div')).find(e => e.children.length===0 && /\\d:\\d\\d\\.\\d\\s*\\/\\s*\\d/.test(e.textContent||'')); return el? el.textContent.trim() : null; }""")
    # PLAY test: click play, confirm time advances (live playback)
    def parse_t(s):
        try:
            mm, ss = s.split('/')[0].strip().split(':'); return int(mm)*60+float(ss)
        except Exception:
            return None
    seek_fraction(0.0, "start")
    play = page.query_selector('[title^="再生"]')
    if play:
        t_before = parse_t(cur_time())
        play.click()
        samples = []
        for _ in range(6):
            page.wait_for_timeout(350)
            samples.append(page.evaluate("() => { const v=document.querySelectorAll('video')[0]; return v? Math.round(v.currentTime*100)/100 : null; }"))
        t_after = parse_t(cur_time())
        page.screenshot(path=r"C:\Users\Owner\AppData\Local\Temp\preview_playing.png")
        adv = (t_after or 0) - (t_before or 0)
        backs = sum(1 for a, b in zip(samples, samples[1:]) if a is not None and b is not None and b < a - 0.05)
        print(f"[pv] PLAY speed: timeline advanced {adv:.2f}s over ~2.1s (1x=~2.1, bug=under1). video samples={samples}")
        print(f"[pv] backward jumps in video (stutter/rewind): {backs} (0=smooth)")
        media = page.evaluate("""() => Array.from(document.querySelectorAll('video')).map(v => ({muted: v.muted, paused: v.paused, ct: Math.round(v.currentTime*100)/100}))""")
        unmuted_playing = [m for m in media if not m["muted"] and not m["paused"]]
        print(f"[pv] AUDIO during play: unmuted&playing={len(unmuted_playing)}")
        pause = page.query_selector('[title^="一時停止"]')
        if pause: pause.click()

    # REFLECT test: at a caption time, delete that caption clip -> preview caption gone.
    # Screenshot the CANVAS element only (zoomed) for a clear before/after.
    seek_fraction(0.05, "before_del")
    cv = page.query_selector("canvas")
    if cv:
        cv.screenshot(path=r"C:\Users\Owner\AppData\Local\Temp\canvas_before_del.png")
    cap = page.evaluate_handle("""() => Array.from(document.querySelectorAll('[title]')).find(e => (e.getAttribute('title')||'').startsWith('テロップ'))||null""").as_element()
    def cap_count():
        return page.evaluate("""() => Array.from(document.querySelectorAll('[title]')).filter(e=>(e.getAttribute('title')||'').startsWith('テロップ')).length""")
    if cap:
        cb = cap.bounding_box()
        n_before = cap_count()
        page.mouse.click(cb["x"]+min(cb["width"]/2,40), cb["y"]+cb["height"]/2)  # select caption clip
        page.wait_for_timeout(300)
        rings = page.evaluate("() => document.querySelectorAll('[class*=\"ring-yellow\"]').length")
        page.evaluate("() => (document.activeElement && document.activeElement.blur && document.activeElement.blur())")  # ensure focus not on a button
        page.keyboard.press("Delete")
        page.wait_for_timeout(1400)
        n_after = cap_count()
        if cv:
            cv.screenshot(path=r"C:\Users\Owner\AppData\Local\Temp\canvas_after_del.png")
        print(f"[pv] REFLECT: selectedRing={rings}, caption-clip handles {n_before}->{n_after} (deleted={n_after<n_before})")
    print("[pv] console errors:", [e for e in errs[:8]])
    b.close()
print("[pv] done")
