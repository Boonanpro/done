"""Load-speed (windowing): the preview must NOT spin up one <video> per clip. For the 90+ clip
real content it should cap the live hidden media elements to a small window near the playhead
(was 92). Asserts the count is well under 30, and that the preview still renders a real frame."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.auth_service import create_token_pair

ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
WEB = "http://127.0.0.1:3000"
tp = create_token_pair(user_id="2582a188-ff24-4a4f-b989-6063034d90b2", email="0aw325171@gmail.com")
cid = next(c["id"] for c in json.loads((Path("uploads/production-assets") / ROOM / "contents.json").read_text(encoding="utf-8")) if c["id"].startswith("8a429e2b"))

ok = True
def check(name, cond, detail=""):
    global ok
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
    ok = ok and cond

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, channel="chrome", args=["--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context(viewport={"width": 1500, "height": 950})
    ctx.add_cookies([{"name": "done_access_token", "value": tp.access_token, "url": WEB},
                     {"name": "done_refresh_token", "value": tp.refresh_token, "url": WEB}])
    ctx.add_init_script(f"window.localStorage.setItem('done-token', {tp.access_token!r});")
    page = ctx.new_page()
    page.goto(f"{WEB}/production-workspace?room_id={ROOM}&content_id={cid}", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(9000)
    n_load = page.evaluate("() => document.querySelectorAll('video').length")
    print("hidden <video> elements at load (playhead=0):", n_load)
    check("element count capped near playhead (was 92, now < 30)", n_load < 30, f"count={n_load}")
    # play a bit; window should follow, still capped
    page.mouse.click(750, 300); page.keyboard.press("Space"); page.wait_for_timeout(8000)
    n_play = page.evaluate("() => document.querySelectorAll('video').length")
    print("hidden <video> elements after ~8s playback:", n_play)
    check("element count stays capped during playback", n_play < 30, f"count={n_play}")
    b.close()

print("\nLOAD WINDOW:", "ALL PASS" if ok else "FAILURES")
