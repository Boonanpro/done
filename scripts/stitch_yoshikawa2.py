import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright
import os, time

REFS = r"D:/dan-workspace/hp-projects/yoshikawa-v2/refs"
os.makedirs(REFS, exist_ok=True)

PROMPT = """A landing page for 吉川特装自動車 (Yoshikawa Tokuso Jidosha), a special vehicle repair and customization workshop in Japan's San'in region.

Style: Industrial workshop aesthetic. Dark steel-gray background (not pure black). Safety-orange accent color (#f97316 style) used sparingly for CTAs and highlights. Bold condensed Japanese typography for headlines (Zen Kaku Gothic New 900 weight). Monospace font for numbers.

Hero: Full-bleed dark hero with workshop/vehicle photography in background (with dark overlay). Left-aligned large headline "山陰で唯一の新明和認定サービス工場". Phone number CTA prominently displayed. NOT centered corporate style.

Sections needed:
1. Hero with background image, headline, phone CTA
2. Credibility bar with numbers: 創業38年, 新明和認定, 山陰唯一
3. Service vehicles grid (dump truck, garbage truck, crane truck, power gate, snow cat) with real photos
4. Services: repair, maintenance, customization, paint
5. Workshop equipment showcase (lift, paint booth, welding)
6. Contact section with phone prominently

Avoid: Corporate blue, centered hero, generic SaaS feel, pastel colors, illustrations.

Reference: DRIFT Car Paint Restoration design on Dribbble - black + orange + huge condensed headline - but in Japanese and for special vehicles."""

# JS to collect interactive elements across shadow DOM
COLLECT = r"""
() => {
  const out = {buttons: [], textareas: [], editables: []};
  const walk = (root) => {
    if (!root) return;
    const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
    for (const el of all) {
      const tag = el.tagName;
      if (tag === 'BUTTON') {
        const r = el.getBoundingClientRect();
        if (r.width>0 && r.height>0) out.buttons.push({
          text:(el.innerText||'').trim().slice(0,80),
          aria:el.getAttribute('aria-label')||'',
          x:r.x+r.width/2, y:r.y+r.height/2, w:r.width, h:r.height
        });
      }
      if (tag === 'TEXTAREA') {
        const r = el.getBoundingClientRect();
        out.textareas.push({ph:el.placeholder||'', x:r.x+r.width/2, y:r.y+r.height/2, w:r.width, h:r.height});
      }
      if (el.getAttribute && el.getAttribute('contenteditable')==='true') {
        const r = el.getBoundingClientRect();
        out.editables.push({x:r.x+r.width/2, y:r.y+r.height/2, w:r.width, h:r.height});
      }
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);
  return out;
};
"""

def find_frame(page):
    # The UI frame is the google companion (not the stitch top)
    for f in page.frames:
        if 'app-companion' in f.url or 'appspot' in f.url:
            return f
    return page.frames[-1]

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=r"D:/done/.playwright-stitch",
        headless=False,
        viewport={"width": 1440, "height": 900},
        args=['--disable-blink-features=AutomationControlled'],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    print("[1] goto")
    page.goto("https://stitch.withgoogle.com/", wait_until="networkidle")
    page.wait_for_timeout(6000)
    page.screenshot(path=os.path.join(REFS, "stitch-00-loaded.png"), full_page=True)

    frame = find_frame(page)
    print("frame:", frame.url[:100])
    data = frame.evaluate(COLLECT)
    print(f"buttons={len(data['buttons'])} textareas={len(data['textareas'])} editables={len(data['editables'])}")
    for b in data['buttons']:
        print(f"  BTN ({int(b['x'])},{int(b['y'])}) aria='{b['aria']}' text='{b['text']}'")
    for t in data['textareas']:
        print(f"  TA ({int(t['x'])},{int(t['y'])}) {t['w']:.0f}x{t['h']:.0f} ph='{t['ph']}'")
    for e in data['editables']:
        print(f"  CE ({int(e['x'])},{int(e['y'])}) {e['w']:.0f}x{e['h']:.0f}")

    # Try to click Web mode: look for button with text 'Web' or 'ウェブ'
    print("[2] Web toggle")
    for b in data['buttons']:
        t = b['text'].lower()
        if t == 'web' or 'ウェブ' in b['text']:
            page.mouse.click(b['x'], b['y'])
            print("  clicked Web at", b['x'], b['y'])
            page.wait_for_timeout(1000)
            break

    # Find the main prompt textarea (largest one, typically)
    data = frame.evaluate(COLLECT)
    target = None
    if data['textareas']:
        target = max(data['textareas'], key=lambda t: t['w']*t['h'])
        print(f"[3] prompt TA at ({int(target['x'])},{int(target['y'])}) size {target['w']:.0f}x{target['h']:.0f}")
    elif data['editables']:
        target = max(data['editables'], key=lambda t: t['w']*t['h'])
        print(f"[3] prompt CE at ({int(target['x'])},{int(target['y'])})")

    if not target:
        print("NO TARGET")
    else:
        page.mouse.click(target['x'], target['y'])
        page.wait_for_timeout(500)
        page.keyboard.type(PROMPT, delay=2)
        page.wait_for_timeout(800)
        page.screenshot(path=os.path.join(REFS, "stitch-02-prompt-entered.png"), full_page=True)
        print("[4] submit (Ctrl+Enter)")
        page.keyboard.press("Control+Enter")
        page.wait_for_timeout(1500)
        # Also try Enter if nothing happened
        # Check for a send button
        data = frame.evaluate(COLLECT)
        for b in data['buttons']:
            a = (b['aria'] or '').lower()
            t = (b['text'] or '').lower()
            if 'send' in a or 'submit' in a or 'generate' in t or '送信' in b['text']:
                print("  send btn:", b['aria'], b['text'])
                page.mouse.click(b['x'], b['y'])
                break

        print("[5] wait")
        for i in range(1, 7):
            page.wait_for_timeout(15000)
            page.screenshot(path=os.path.join(REFS, f"stitch-wait-{i}.png"), full_page=True)
            print(f"  wait-{i}")
        page.screenshot(path=os.path.join(REFS, "stitch-result.png"), full_page=True)

        # try clicking result screens
        data = frame.evaluate(COLLECT)
        print(f"[6] post-gen buttons={len(data['buttons'])}")
        clicked = 0
        # click buttons that seem like result cards (large ones, not in nav)
        cand = [b for b in data['buttons'] if b['w']>150 and b['h']>100 and b['y']>200]
        for b in cand[:5]:
            try:
                page.mouse.click(b['x'], b['y'])
                page.wait_for_timeout(1500)
                clicked += 1
                page.screenshot(path=os.path.join(REFS, f"stitch-section-{clicked}.png"), full_page=True)
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
            except Exception as e:
                print("  click err:", e)
        print(f"  clicked {clicked}")

    page.wait_for_timeout(2000)
    ctx.close()
    print("DONE")
