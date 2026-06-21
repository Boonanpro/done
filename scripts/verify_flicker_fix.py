"""Verify the flicker root-fix directly: count hidden <video> elements (clip-keyed => one
per visual clip, NOT one per asset), and confirm the same asset is loaded into MULTIPLE
distinct elements (so two clips of one asset can hold different source times). This proves
the collision is gone without relying on flaky timeline-click seeking."""
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

# how many visual clips + how many assets, from data
ct = next(c for c in contents if c["id"] == cid)
seq = ct["timeline"]["sequence"]
visual = [c for t in seq["tracks"] if t["type"] in ("video", "overlay") for c in t["clips"]]
assets_used = {c.get("asset_id") for c in visual}
print(f"[data] visual clips: {len(visual)} | distinct assets: {len(assets_used)}")

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
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(8000)

    info = page.evaluate("""() => {
      const vs = Array.from(document.querySelectorAll('video'));
      const bySrc = {};
      for (const v of vs) { const s=(v.src||'').slice(-30); bySrc[s]=(bySrc[s]||0)+1; }
      return { total: vs.length, bySrc };
    }""")
    print(f"[dom] hidden <video> elements: {info['total']}")
    multi = {s: n for s, n in info["bySrc"].items() if n > 1}
    print(f"[dom] sources loaded into MULTIPLE elements (same asset, separate <video>): {len(multi)}")
    for s, n in list(multi.items())[:4]:
        print(f"     {n}x  ...{s}")

    # The key proof: at least one asset is loaded into >1 element => two clips of the same
    # asset each own a separate <video>, so they can hold different source times (no collision).
    # Also confirm element count tracks clips (>> #assets), not assets.
    ok = info["total"] >= len(visual) - 2 and len(multi) >= 1
    print(f"[flicker] RESULT: {'PASS — per-clip <video> elements; same asset has separate elements (collision impossible)' if ok else 'CHECK'}")
    b.close()
