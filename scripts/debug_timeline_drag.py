"""Drive the real production tab in a headless browser to find why clip
editing (select/drag/trim/delete) does nothing. Mints a token for the owner,
injects it, opens the StyleUp content, screenshots, and inspects clip DOM."""
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
access = tp.access_token
refresh = tp.refresh_token
print("[dbg] minted token len:", len(access))

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    ctx.add_cookies([
        {"name": "done_access_token", "value": access, "url": BASE},
        {"name": "done_refresh_token", "value": refresh, "url": BASE},
    ])
    ctx.add_init_script(f"window.localStorage.setItem('done-token', {access!r});")
    page = ctx.new_page()
    page.on("console", lambda m: print("[console]", m.type, m.text[:200]))
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(7000)
    page.screenshot(path=r"C:\Users\Owner\AppData\Local\Temp\prod_tab.png", full_page=False)
    print("[dbg] screenshot saved")

    info = page.evaluate(r"""
    () => {
      const out = {};
      // all titled elements (clips/annotations carry titles)
      out.titles = Array.from(document.querySelectorAll('[title]')).map(e=>e.getAttribute('title')).filter(t=>t&&t.length<80).slice(0,30);
      // clip candidates: positioned divs with a thumbnail bg OR cursor-grab descendant
      const grabs = Array.from(document.querySelectorAll('[class*="cursor-grab"]'));
      out.grabCount = grabs.length;
      out.probes = [];
      // probe the element stack at the center of each grab handle
      for (const g of grabs.slice(0, 6)) {
        const r = g.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) { out.probes.push({skip:'zero-size', rect:[r.x|0,r.y|0,r.width|0,r.height|0]}); continue; }
        const cx = r.left + Math.min(r.width/2, 30), cy = r.top + r.height/2;
        const stack = document.elementsFromPoint(cx, cy).slice(0,5).map(e=>{
          const cs = getComputedStyle(e);
          return e.tagName.toLowerCase()+'.'+(e.className||'').toString().replace(/\s+/g,'.').slice(0,60)+' [pe='+cs.pointerEvents+']';
        });
        out.probes.push({
          handleRect:[r.x|0,r.y|0,r.width|0,r.height|0],
          handlePE: getComputedStyle(g).pointerEvents,
          stackTopToBottom: stack,
          topIsHandleOrChild: (()=>{const t=document.elementFromPoint(cx,cy); return t? (g.contains(t)||g===t):false;})(),
        });
      }
      return out;
    }
    """)
    import json
    print("[dbg] DOM inspect:\n" + json.dumps(info, ensure_ascii=False, indent=2))

    # Target an actual CLIP body (cursor-grab + gap-1), not an annotation handle.
    clip_body = page.evaluate_handle(r"""
      () => {
        const els = Array.from(document.querySelectorAll('div'));
        return els.find(e => {
          const c = (e.className||'').toString();
          return c.includes('cursor-grab') && c.includes('gap-1');
        }) || null;
      }
    """)
    el = clip_body.as_element()
    print("[dbg] clip body found:", bool(el))
    if el:
        b = el.bounding_box()
        # parent absolute clip div (to watch its left% change)
        before_left = el.evaluate("e => (e.closest('.absolute')?.style.left) || ''")
        cx, cy = b["x"] + b["width"]/2, b["y"] + b["height"]/2
        # 1) plain click -> selection?
        page.mouse.click(cx, cy)
        page.wait_for_timeout(400)
        sel = page.evaluate("() => ({ring: document.querySelectorAll('[class*=\"ring-yellow\"]').length, panel: !!Array.from(document.querySelectorAll('*')).find(e=>e.children.length===0 && (e.textContent||'').trim()==='選択中クリップ')})")
        print("[dbg] after click -> selection:", sel)
        # snapshot ALL clip container lefts (avoid overlapping-clip confusion)
        def all_lefts():
            return page.evaluate("() => Array.from(document.querySelectorAll('.absolute')).map(e=>e.style.left).filter(l=>l && l.includes('%')).sort()")
        lefts_before = all_lefts()
        def selected_left():
            return page.evaluate("() => { const r = document.querySelector('[class*=\"ring-yellow\"]'); const c = r? r.closest('.absolute'):null; return c? c.style.left : null; }")
        sleft_before = selected_left()
        # 2) drag the clip body +300px
        print(f"[dbg] dragging clip body at ({cx:.0f},{cy:.0f}) +300px; selected-left before={sleft_before!r}")
        page.mouse.move(cx, cy)
        page.mouse.down()
        for i in range(1, 13):
            page.mouse.move(cx + 300 * i/12, cy, steps=1)
            page.wait_for_timeout(22)
        page.mouse.up()
        page.wait_for_timeout(700)
        sleft_after = selected_left()
        lefts_after = all_lefts()
        changed = [x for x in zip(sorted(set(lefts_before)), sorted(set(lefts_after))) ] if False else None
        added = sorted(set(lefts_after) - set(lefts_before))
        removed = sorted(set(lefts_before) - set(lefts_after))
        print(f"[dbg] ANY clip moved? lefts added(new positions)={added[:6]} removed(old)={removed[:6]}")
        print(f"[dbg] (selected-left {sleft_before!r}->{sleft_after!r})")
        page.screenshot(path=r"C:\Users\Owner\AppData\Local\Temp\prod_tab_afterdrag.png")
        page.screenshot(path=r"C:\Users\Owner\AppData\Local\Temp\prod_tab_moved.png")
        # 3) delete test: count clips, press Delete, recount
        before_clips = page.evaluate("() => Array.from(document.querySelectorAll('[title]')).filter(e=>/\\d:\\d\\d-\\d:\\d\\d/.test(e.getAttribute('title')||'')).length")
        page.keyboard.press("Delete")
        page.wait_for_timeout(500)
        after_clips = page.evaluate("() => Array.from(document.querySelectorAll('[title]')).filter(e=>/\\d:\\d\\d-\\d:\\d\\d/.test(e.getAttribute('title')||'')).length")
        print(f"[dbg] DELETE test: titled clip-handles {before_clips} -> {after_clips} (decreased={after_clips<before_clips})")

    browser.close()
print("[dbg] done")
