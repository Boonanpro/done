import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright
import os
REFS = r"D:/dan-workspace/hp-projects/yoshikawa-v2/refs"

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

    # Navigate into the most-recent project (the one we just generated)
    # Click the project on the project list
    page.wait_for_timeout(2000)
    page.screenshot(path=os.path.join(REFS, "stitch-home-again.png"), full_page=True)

    # The previous run ended while looking at the canvas with overlays.
    # Simply re-enter most recent project by clicking first project thumbnail.
    # From the home page we saw earlier, there's a project list on left column.
    # Instead, just click the first item in "My Projects".
    frame = None
    for f in page.frames:
        if 'appspot' in f.url:
            frame = f; break

    # Try to click first project card
    COLLECT = r"""
    () => {
      const out = [];
      const walk = r => {
        if (!r) return;
        const all = r.querySelectorAll ? r.querySelectorAll('a,button,[role="button"],li') : [];
        for (const el of all) {
          const rect = el.getBoundingClientRect();
          if (rect.width>50 && rect.height>50 && rect.y>120 && rect.y<700 && rect.x<400) {
            out.push({x:rect.x+rect.width/2, y:rect.y+rect.height/2, w:rect.width, h:rect.height, text:(el.innerText||'').trim().slice(0,60)});
          }
          if (el.shadowRoot) walk(el.shadowRoot);
        }
      };
      walk(document);
      return out;
    };
    """
    items = frame.evaluate(COLLECT) if frame else []
    print("candidates:", len(items))
    for it in items[:10]:
        print(" ", it)
    # click the first candidate likely to be the yoshikawa project
    target = None
    for it in items:
        if '吉川' in it['text'] or 'landing' in it['text'].lower() or 'Yoshikawa' in it['text']:
            target = it; break
    if not target and items:
        target = items[0]
    if target:
        print("click:", target)
        page.mouse.click(target['x'], target['y'])
        page.wait_for_timeout(5000)
    page.screenshot(path=os.path.join(REFS, "stitch-project-open.png"), full_page=True)

    # Close any overlay panels by pressing Escape a couple times
    for _ in range(3):
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    page.screenshot(path=os.path.join(REFS, "stitch-canvas-clean.png"), full_page=True)

    # Zoom to fit via keyboard shortcut (common: 0 or F or Shift+1)
    for key in ["0", "1", "f"]:
        page.keyboard.press(key)
        page.wait_for_timeout(500)
    page.screenshot(path=os.path.join(REFS, "stitch-canvas-zoom.png"), full_page=True)

    # Scroll around canvas
    page.mouse.move(720, 450)
    for i, dy in enumerate([-500, -500, 1000, 500]):
        page.mouse.wheel(0, dy)
        page.wait_for_timeout(700)
        page.screenshot(path=os.path.join(REFS, f"stitch-section-{i+1}.png"), full_page=True)

    page.wait_for_timeout(1000)
    ctx.close()
    print("DONE")
