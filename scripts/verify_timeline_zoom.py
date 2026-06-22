"""Slice 1: verify the timeline has trailing space (last clip not flush to the right edge)
and the zoom +/-/fit buttons work."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.auth_service import create_token_pair

ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
BASE = "http://127.0.0.1:3000"
tp = create_token_pair(user_id="2582a188-ff24-4a4f-b989-6063034d90b2", email="0aw325171@gmail.com")
contents = json.loads((Path("uploads/production-assets") / ROOM / "contents.json").read_text(encoding="utf-8"))
cid = next(c["id"] for c in contents if c["id"].startswith("8a429e2b"))

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, channel="chrome")
    ctx = b.new_context(viewport={"width": 1500, "height": 950})
    ctx.add_cookies([{"name": "done_access_token", "value": tp.access_token, "url": BASE},
                     {"name": "done_refresh_token", "value": tp.refresh_token, "url": BASE}])
    ctx.add_init_script(f"window.localStorage.setItem('done-token', {tp.access_token!r});")
    page = ctx.new_page()
    page.goto(f"{BASE}/production-workspace?room_id={ROOM}&content_id={cid}", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(8000)

    info = page.evaluate("""() => {
      const bars = Array.from(document.querySelectorAll('div[style*="left:"][style*="width:"]'));
      if (!bars.length) return null;
      let maxRight = 0;
      for (const b of bars) { const l = parseFloat(b.style.left)||0, w = parseFloat(b.style.width)||0; if (l+w > maxRight) maxRight = l+w; }
      return { clipCount: bars.length, maxRightPct: Math.round(maxRight) };
    }""")
    print("clip max right %:", info)
    # trailing space => last clip's right edge < ~100% of the track
    if info:
        ok_space = info["maxRightPct"] <= 96
        print(f"[PASS] trailing space present (max right {info['maxRightPct']}% < 96%)" if ok_space
              else f"[FAIL] no trailing space (max right {info['maxRightPct']}%)")

    zin = page.query_selector("button[title='ズームイン']")
    fit = page.query_selector("button[title='全体にフィット']")
    print("zoom-in btn:", bool(zin), "| fit btn:", bool(fit))
    if zin and fit:
        before = fit.inner_text()
        zin.click(); page.wait_for_timeout(300)
        after = fit.inner_text()
        print(f"[{'PASS' if after != before else 'FAIL'}] zoom-in changed level {before} -> {after}")
        fit.click(); page.wait_for_timeout(300)
        reset = fit.inner_text()
        print(f"[{'PASS' if reset == '100%' else 'FAIL'}] fit reset to {reset}")
    b.close()
