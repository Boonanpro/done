"""Slice 2: verify cut-at-playhead. Loads the workspace, seeks the playhead to a spot where
several clips are active, presses 'S' (no selection -> split every clip under the playhead),
and asserts the timeline bar count increased. Also confirms the scissors button exists. A
follow-up press at a NEW spot must keep increasing (idempotent only at the same exact time)."""
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

    def bar_count():
        return page.evaluate("""() => Array.from(document.querySelectorAll('div[style*="left:"][style*="width:"]'))
            .filter(b => (parseFloat(b.style.width)||0) > 0).length""")

    cut_btn = page.query_selector("button[title='再生ヘッドで分割 (S)']")
    print("scissors button present:", bool(cut_btn))

    def seek_frac(frac):
        spot = page.evaluate("""(frac) => {
          const lanes = Array.from(document.querySelectorAll('div')).filter(e => {
            const c=(e.className||'').toString();
            return c.includes('bg-neutral-900') && e.getBoundingClientRect().width > 300; });
          const lane = lanes[lanes.length-1]; if(!lane) return null;
          const r = lane.getBoundingClientRect(); return {x: r.left + r.width*frac, y: r.top + r.height/2};
        }""", frac)
        if spot:
            page.mouse.click(spot["x"], spot["y"]); page.wait_for_timeout(600)

    before = bar_count()
    # clear any selection, seek to ~40% (well inside the content, multiple lanes active)
    page.keyboard.press("Escape")
    seek_frac(0.40)
    page.keyboard.press("s")
    page.wait_for_timeout(700)
    after = bar_count()
    print(f"bars before={before}  after S @40%={after}  delta={after-before}")
    ok1 = after > before
    print(f"[{'PASS' if ok1 else 'FAIL'}] S split added bars (every clip under playhead)")

    # a second cut at a different spot keeps adding
    seek_frac(0.65)
    page.keyboard.press("s")
    page.wait_for_timeout(700)
    after2 = bar_count()
    print(f"bars after 2nd S @65%={after2}  delta={after2-after}")
    ok2 = after2 > after
    print(f"[{'PASS' if ok2 else 'FAIL'}] 2nd cut at a new spot added more bars")

    # re-pressing S at the SAME spot must NOT keep splitting (already a boundary there)
    page.keyboard.press("s")
    page.wait_for_timeout(500)
    after3 = bar_count()
    ok3 = after3 == after2
    print(f"bars after repeat S @same={after3}  [{'PASS' if ok3 else 'FAIL'}] no-op on an existing boundary")

    print("\nSPLIT:", "ALL PASS" if (cut_btn and ok1 and ok2 and ok3) else "FAILURES")
    b.close()

# Self-clean: this test autosaves splits into the real content. Merge any '__s_' halves back
# into their base (continuous ranges => exact reconstruction) so re-running is non-destructive.
cpath = Path("uploads/production-assets") / ROOM / "contents.json"
data = json.loads(cpath.read_text(encoding="utf-8"))
ct = next(c for c in data if c["id"] == cid)
removed = 0
for tr in ct["timeline"]["sequence"]["tracks"]:
    clips = tr.get("clips", [])
    rights = [c for c in clips if "__s_" in str(c.get("id", ""))]
    for right in rights:
        base_id = str(right["id"]).split("__s_")[0]
        base = next((c for c in clips if c.get("id") == base_id), None)
        if base:
            base["timeline_end"] = right["timeline_end"]
            if "source_end" in right:
                base["source_end"] = right["source_end"]
    if rights:
        tr["clips"] = [c for c in clips if "__s_" not in str(c.get("id", ""))]
        removed += len(rights)
if removed:
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[cleanup] merged {removed} split half/halves back into base clips (content restored)")
