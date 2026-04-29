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
    print("URL:", page.url)
    print("Title:", page.title())
    page.screenshot(path=os.path.join(REFS, "stitch-inspect.png"), full_page=True)

    btns = page.locator("button").all()
    print(f"\n{len(btns)} buttons:")
    for i, b in enumerate(btns[:50]):
        try:
            txt = (b.inner_text() or "").strip()[:50]
            aria = b.get_attribute("aria-label") or ""
            vis = b.is_visible()
            print(f"  [{i}] vis={vis} text='{txt}' aria='{aria[:40]}'")
        except Exception:
            pass

    ta = page.locator("textarea").all()
    print(f"\n{len(ta)} textareas")
    for i, t in enumerate(ta):
        try:
            print(f"  ta[{i}] vis={t.is_visible()} ph='{t.get_attribute('placeholder')}'")
        except: pass

    ce = page.locator('[contenteditable="true"]').all()
    print(f"\n{len(ce)} contenteditable: vis={[c.is_visible() for c in ce]}")

    for role in ["tab", "radio", "switch"]:
        els = page.get_by_role(role).all()
        print(f"\nrole={role}: {len(els)}")
        for i, e in enumerate(els[:10]):
            try:
                print(f"  [{i}] '{(e.inner_text() or '')[:40]}'")
            except: pass

    print(f"\nframes: {len(page.frames)}")
    for f in page.frames:
        print(" -", f.url[:80])

    # Dump body text first 2000 chars
    print("\n--- BODY TEXT ---")
    try:
        print(page.locator("body").inner_text()[:2000])
    except: pass

    page.wait_for_timeout(2000)
    ctx.close()
