from playwright.sync_api import sync_playwright
import os, json
REFS = r"D:/dan-workspace/hp-projects/yoshikawa-v2/refs"

JS = r"""
() => {
  const results = {buttons: [], textareas: [], editables: []};
  const walk = (root) => {
    if (!root) return;
    const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
    for (const el of all) {
      const tag = el.tagName;
      if (tag === 'BUTTON') {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
          results.buttons.push({
            text: (el.innerText||'').trim().slice(0,60),
            aria: el.getAttribute('aria-label')||'',
            x: r.x+r.width/2, y: r.y+r.height/2, w: r.width, h: r.height
          });
        }
      }
      if (tag === 'TEXTAREA' || tag === 'INPUT') {
        const r = el.getBoundingClientRect();
        results.textareas.push({
          tag, type: el.type||'', ph: el.placeholder||'',
          x: r.x+r.width/2, y: r.y+r.height/2, w: r.width, h: r.height
        });
      }
      if (el.getAttribute && el.getAttribute('contenteditable') === 'true') {
        const r = el.getBoundingClientRect();
        results.editables.push({x: r.x+r.width/2, y: r.y+r.height/2, w: r.width, h: r.height});
      }
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);
  return results;
}
"""

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=r"D:/done/.playwright-stitch",
        headless=False,
        viewport={"width": 1440, "height": 900},
        args=['--disable-blink-features=AutomationControlled'],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://stitch.withgoogle.com/", wait_until="networkidle")
    page.wait_for_timeout(5000)

    print("FRAMES:", len(page.frames))
    for i, f in enumerate(page.frames):
        print(f"[f{i}] {f.url[:100]}")
        try:
            d = f.evaluate(JS)
            print(f"  buttons={len(d['buttons'])} textareas={len(d['textareas'])} editables={len(d['editables'])}")
            for b in d['buttons'][:30]:
                print(f"    BTN ({int(b['x'])},{int(b['y'])}) aria='{b['aria'][:40]}' text='{b['text']}'")
            for t in d['textareas']:
                print(f"    INP {t['tag']} ({int(t['x'])},{int(t['y'])}) {t['w']:.0f}x{t['h']:.0f} ph='{t['ph']}'")
            for e in d['editables']:
                print(f"    CE ({int(e['x'])},{int(e['y'])}) {e['w']:.0f}x{e['h']:.0f}")
        except Exception as ex:
            print("  err:", ex)
    data = page.evaluate(JS)
    print("MAIN BUTTONS:", len(data['buttons']))
    for b in data['buttons'][:40]:
        print(f"  ({int(b['x'])},{int(b['y'])}) {b['w']:.0f}x{b['h']:.0f} aria='{b['aria'][:40]}' text='{b['text']}'")
    print("TEXTAREAS/INPUTS:", len(data['textareas']))
    for t in data['textareas']:
        print(f"  {t['tag']} ({int(t['x'])},{int(t['y'])}) {t['w']:.0f}x{t['h']:.0f} ph='{t['ph']}'")
    print("EDITABLES:", len(data['editables']))
    for e in data['editables']:
        print(f"  ({int(e['x'])},{int(e['y'])}) {e['w']:.0f}x{e['h']:.0f}")

    page.wait_for_timeout(1500)
    ctx.close()
