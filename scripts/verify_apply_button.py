"""Verify Stage 2 unified apply button: it is ENABLED when the content has mechanical
edits (styled captions on 8a429e2b), shows the right badges, and is no longer gated on
outputs.length. Read-only UI check (does not click apply to avoid spawning jobs)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.auth_service import create_token_pair

USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"
EMAIL = "0aw325171@gmail.com"
ROOM = "bd05fcc0-c143-4d1c-828e-7624e087b6c1"
CONTENT = "8a429e2b"  # has styled captions from Stage 1 test
BASE = "http://127.0.0.1:3000"
tp = create_token_pair(user_id=USER_ID, email=EMAIL)

# resolve full content id
import json
contents = json.loads((Path("uploads/production-assets") / ROOM / "contents.json").read_text(encoding="utf-8"))
cid = next(c["id"] for c in contents if c["id"].startswith(CONTENT))
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
    page = ctx.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(7000)

    # find the unified apply button
    btn = page.query_selector("button:has-text('適用 / 作り直す')")
    print("[btn] present:", bool(btn))
    if btn:
        disabled = page.evaluate("(b)=>b.disabled", btn)
        print("[btn] disabled:", disabled, "(expect False — styled captions = mechanical edits)")
    # badges
    for label in ["手編集を反映", "文章で指示", "指示クリップ"]:
        el = page.query_selector(f"span:has-text('{label}')")
        print(f"[badge] {label}:", bool(el))
    # type into textarea -> button should still be enabled, "文章で指示" badge appears
    ta = page.query_selector("textarea[placeholder*='言い直し']")
    if ta:
        ta.fill("テロップを少し小さく")
        page.wait_for_timeout(500)
        el = page.query_selector("span:has-text('文章で指示')")
        print("[after-type] 文章で指示 badge:", bool(el))
    print("[done]")
    b.close()
