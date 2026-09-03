"""Load the production editor with ALL content-save PATCH requests ABORTED, so the
disk file cannot be clobbered by auto-save. Confirms the editor faithfully loads the
restored 3 caption clips. Pure read of the user's data — saves are blocked."""
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
    try:
        b = p.chromium.launch(headless=True, channel="chrome", args=["--autoplay-policy=no-user-gesture-required"])
    except Exception:
        b = p.chromium.launch(headless=True, channel="msedge", args=["--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context(viewport={"width": 1400, "height": 900})
    ctx.add_cookies([{"name": "done_access_token", "value": tp.access_token, "url": BASE},
                     {"name": "done_refresh_token", "value": tp.refresh_token, "url": BASE}])
    ctx.add_init_script(f"window.localStorage.setItem('done-token', {tp.access_token!r});")

    blocked = {"n": 0}
    def guard(route):
        req = route.request
        if req.method in ("PATCH", "POST", "PUT") and "/production-assets/contents" in req.url:
            blocked["n"] += 1
            return route.abort()
        return route.continue_()
    ctx.route("**/production-assets/contents**", guard)

    page = ctx.new_page()
    errs = []
    page.on("console", lambda m: errs.append(m.text[:160]) if m.type == "error" else None)
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(9000)

    cap_handles = page.evaluate("""() => Array.from(document.querySelectorAll('[title]'))
        .filter(e=>(e.getAttribute('title')||'').startsWith('テロップ'))
        .map(e=>e.getAttribute('title'))""")
    print(f"[load] caption clip handles loaded (expect 3): {len(cap_handles)}")
    for t in cap_handles:
        print("   -", t[:60])
    print(f"[load] save requests blocked (disk protected): {blocked['n']}")
    print("[load] console errors:", [e for e in errs[:8]])
    b.close()
print("[load] done")
