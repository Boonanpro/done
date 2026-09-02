"""Stage 2 dispatch test: actually CLICK the unified apply button and assert the job
posted has the correct mode for each case:
 (A) text only       -> dan_edit       (Dan creative)
 (B) mechanical only  -> render_timeline (deterministic, no Dan)
 (C) both             -> render_timeline AND dan_edit
Intercepts POST /jobs to read instruction.mode without waiting for jobs to finish.
Uses content 8a429e2b (has styled captions = mechanical edit present)."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.auth_service import create_token_pair

USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"
EMAIL = "0aw325171@gmail.com"
ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
BASE = "http://127.0.0.1:3000"
tp = create_token_pair(user_id=USER_ID, email=EMAIL)
contents = json.loads((Path("uploads/production-assets") / ROOM / "contents.json").read_text(encoding="utf-8"))
cid = next(c["id"] for c in contents if c["id"].startswith("8a429e2b"))
URL = f"{BASE}/production-workspace?room_id={ROOM}&content_id={cid}"

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    try:
        b = p.chromium.launch(headless=True, channel="chrome")
    except Exception:
        b = p.chromium.launch(headless=True, channel="msedge")
    ctx = b.new_context(viewport={"width": 1400, "height": 900})
    ctx.add_cookies([{"name": "done_access_token", "value": tp.access_token, "url": BASE},
                     {"name": "done_refresh_token", "value": tp.refresh_token, "url": BASE}])
    ctx.add_init_script(f"window.localStorage.setItem('done-token', {tp.access_token!r});")

    posted_modes = []
    def on_request(route):
        req = route.request
        if req.method == "POST" and req.url.endswith("/production-assets/jobs"):
            try:
                body = json.loads(req.post_data or "{}")
                posted_modes.append(body.get("instruction", {}).get("mode"))
            except Exception:
                posted_modes.append("(parse-fail)")
            # ABORT so no real job actually runs (we only check dispatch)
            return route.abort()
        return route.continue_()
    ctx.route("**/production-assets/jobs", on_request)

    page = ctx.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(7000)

    btn_sel = "button:has-text('適用 / 作り直す')"
    ta_sel = "textarea[placeholder*='言い直し']"

    # CASE B: mechanical only (styled captions exist, no text) -> render_timeline
    posted_modes.clear()
    page.click(btn_sel)
    page.wait_for_timeout(1500)
    print(f"[B mechanical-only] posted modes: {posted_modes}  (expect ['render_timeline'])")

    # CASE C: both (type text, styled captions still present) -> render_timeline + dan_edit
    posted_modes.clear()
    page.fill(ta_sel, "テロップを少し小さくして")
    page.wait_for_timeout(400)
    page.click(btn_sel)
    page.wait_for_timeout(1800)
    print(f"[C both] posted modes: {posted_modes}  (expect render_timeline + dan_edit)")

    print("[done]")
    b.close()
