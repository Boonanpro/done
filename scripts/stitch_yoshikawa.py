from playwright.sync_api import sync_playwright
import time, os

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

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=r"D:/done/.playwright-stitch",
        headless=False,
        viewport={"width": 1440, "height": 900},
        args=['--disable-blink-features=AutomationControlled'],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    print("[1] goto stitch")
    page.goto("https://stitch.withgoogle.com/", wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    page.screenshot(path=os.path.join(REFS, "stitch-00-loaded.png"), full_page=True)
    print("  url:", page.url, "title:", page.title())

    # Try to find Web/App toggle
    print("[2] look for Web toggle")
    try:
        # common patterns
        for sel in ['button:has-text("Web")', 'text=/^Web$/', '[role="tab"]:has-text("Web")', 'label:has-text("Web")']:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    el.click(timeout=2000)
                    print("  clicked Web via", sel)
                    page.wait_for_timeout(800)
                    break
            except Exception as e:
                pass
    except Exception as e:
        print("  web toggle err:", e)

    page.screenshot(path=os.path.join(REFS, "stitch-01-web-mode.png"), full_page=True)

    # Find the prompt input
    print("[3] find input")
    input_el = None
    for sel in ['textarea', '[contenteditable="true"]', 'input[type="text"]']:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                input_el = loc
                print("  found:", sel)
                break
        except Exception:
            pass

    if not input_el:
        print("  NO INPUT FOUND")
        page.screenshot(path=os.path.join(REFS, "stitch-ERROR-no-input.png"), full_page=True)
    else:
        input_el.click()
        page.wait_for_timeout(300)
        input_el.fill(PROMPT)
        page.wait_for_timeout(500)
        page.screenshot(path=os.path.join(REFS, "stitch-02-prompt-entered.png"), full_page=True)
        print("[4] submit")
        # Try Ctrl+Enter then Enter
        submitted = False
        for sel in ['button[type="submit"]', 'button:has-text("Generate")', 'button:has-text("Send")', 'button[aria-label*="end" i]', 'button[aria-label*="ubmit" i]']:
            try:
                b = page.locator(sel).first
                if b.count() > 0 and b.is_visible() and b.is_enabled():
                    b.click()
                    submitted = True
                    print("  submitted via", sel)
                    break
            except Exception:
                pass
        if not submitted:
            try:
                input_el.press("Control+Enter")
                print("  tried Ctrl+Enter")
            except Exception:
                pass
            try:
                input_el.press("Enter")
                print("  tried Enter")
            except Exception:
                pass

        print("[5] wait & snapshot")
        for i in range(1, 7):
            page.wait_for_timeout(15000)
            path = os.path.join(REFS, f"stitch-wait-{i}.png")
            try:
                page.screenshot(path=path, full_page=True)
                print(f"  wait-{i} ok")
            except Exception as e:
                print(f"  wait-{i} err", e)

        page.screenshot(path=os.path.join(REFS, "stitch-result.png"), full_page=True)
        print("[6] result saved")

        # Try clicking generated screens
        print("[7] try clicking screens")
        clicked = 0
        for sel in ['[data-testid*="screen"]', '[class*="screen"]', '[class*="Screen"]', 'img[alt*="screen" i]', '[class*="card"]', 'figure']:
            try:
                items = page.locator(sel)
                n = items.count()
                if n > 0:
                    print(f"  {sel} x{n}")
                    for idx in range(min(n, 6)):
                        try:
                            items.nth(idx).scroll_into_view_if_needed(timeout=1500)
                            items.nth(idx).click(timeout=2000)
                            page.wait_for_timeout(1500)
                            clicked += 1
                            page.screenshot(path=os.path.join(REFS, f"stitch-section-{clicked}.png"), full_page=True)
                            # close modal if any
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(500)
                        except Exception as e:
                            pass
                    if clicked > 0:
                        break
            except Exception:
                pass
        print(f"  clicked {clicked} sections")

    page.wait_for_timeout(2000)
    ctx.close()
    print("DONE")
