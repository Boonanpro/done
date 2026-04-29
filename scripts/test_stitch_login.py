"""Test Stitch (stitch.withgoogle.com) login via Playwright."""

from playwright.sync_api import sync_playwright
import time

def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir="D:/done/.playwright-stitch",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()

        # Step 1: Open Stitch
        print("[1] Opening https://stitch.withgoogle.com/ ...")
        page.goto("https://stitch.withgoogle.com/", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(5)  # Wait for iframe to fully load
        print(f"    URL: {page.url}")
        print(f"    Title: {page.title()}")

        # The app lives inside an iframe - get the frame
        print("\n[DEBUG] Looking for iframe...")
        frames = page.frames
        print(f"    Total frames: {len(frames)}")
        for i, f in enumerate(frames):
            print(f"    Frame {i}: {f.url[:120]}")

        # Find the app iframe
        app_frame = None
        for f in frames:
            if "app-companion" in f.url or "appspot" in f.url:
                app_frame = f
                break

        if app_frame is None:
            print("    No app iframe found, trying with main page frame...")
            app_frame = page

        # Inspect iframe content
        print(f"\n[DEBUG] App frame URL: {app_frame.url[:120]}")
        print("[DEBUG] Looking for clickable elements in iframe...")

        elements_info = app_frame.evaluate("""
            () => {
                const els = document.querySelectorAll('a, button, [role="button"], [tabindex]');
                const results = [];
                for (const el of els) {
                    const text = (el.textContent || '').trim().substring(0, 100);
                    const tag = el.tagName;
                    const href = el.getAttribute('href') || '';
                    const cls = (el.className ? String(el.className) : '').substring(0, 80);
                    const aria = el.getAttribute('aria-label') || '';
                    if (text || href || aria) {
                        results.push({tag, text, href, cls, aria});
                    }
                }
                return results.slice(0, 30);
            }
        """)
        for r in elements_info:
            print(f"  <{r['tag']}> text='{r['text']}' href='{r['href']}' aria='{r['aria']}'")

        # Also look for text containing "Try"
        print("\n[DEBUG] Elements containing 'try' or 'Try':")
        try_els = app_frame.evaluate("""
            () => {
                const all = document.querySelectorAll('*');
                const found = [];
                for (const el of all) {
                    // Only direct text (not child text)
                    const directText = Array.from(el.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim())
                        .join('');
                    if (directText.toLowerCase().includes('try')) {
                        const rect = el.getBoundingClientRect();
                        found.push({
                            tag: el.tagName,
                            text: directText.substring(0, 80),
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            w: Math.round(rect.width),
                            h: Math.round(rect.height),
                            cls: (el.className ? String(el.className) : '').substring(0, 80)
                        });
                    }
                }
                return found.slice(0, 10);
            }
        """)
        for r in try_els:
            print(f"  <{r['tag']}> text='{r['text']}' pos=({r['x']},{r['y']}) size=({r['w']}x{r['h']})")

        # Try to find and click "Try now" in the iframe
        print("\n[2] Attempting to click 'Try now' in iframe...")
        try:
            # Try locator within frame
            btn = app_frame.locator("text=/Try now/i").first
            if btn.count() > 0:
                print("    Found 'Try now' via locator!")
                # Listen for popup
                with context.expect_page(timeout=15000) as new_page_info:
                    btn.click()
                new_page = new_page_info.value
                print(f"    New page opened: {new_page.url}")
                time.sleep(3)
                try:
                    new_page.wait_for_load_state("networkidle", timeout=15000)
                except:
                    pass
                new_page.screenshot(path="D:/done/tmp_stitch_login.png")
                print("[3] Screenshot saved")
                active_page = new_page
            else:
                print("    'Try now' not found in iframe either.")
                # Let's try just clicking the area on the main page
                # From the screenshot, "Try now" is at approximately top-right
                # The iframe might cover the full page, so click within iframe
                print("    Trying frame_locator approach...")
                fl = page.frame_locator("iframe").locator("text=/Try now/i").first
                if fl.count() > 0:
                    print("    Found via frame_locator!")
                    fl.click()
                    time.sleep(5)
                else:
                    print("    Not found via frame_locator either.")
                    # Last resort: dump all visible text
                    all_text = app_frame.evaluate("() => document.body.innerText.substring(0, 2000)")
                    print(f"    Page text:\n{all_text}")

                active_page = page
                page.screenshot(path="D:/done/tmp_stitch_login.png")
        except Exception as e:
            print(f"    Error: {e}")
            # The popup might not have appeared - check pages
            all_pages = context.pages
            print(f"    Pages: {len(all_pages)}")
            for i, pg in enumerate(all_pages):
                print(f"      Page {i}: {pg.url}")
            active_page = all_pages[-1]
            try:
                active_page.wait_for_load_state("networkidle", timeout=10000)
            except:
                pass
            active_page.screenshot(path="D:/done/tmp_stitch_login.png")
            print("    Screenshot saved")

        # Check final state
        url = active_page.url
        print(f"\n[CHECK] Active page URL: {url}")

        if "accounts.google.com" in url:
            print("[4] Google login page detected!")
            try:
                email_input = active_page.locator('input[type="email"]').first
                if email_input.count() > 0:
                    email_input.fill("0aw325171@gmail.com")
                    print("    Email entered: 0aw325171@gmail.com")
                    time.sleep(1)
                    active_page.screenshot(path="D:/done/tmp_stitch_login2.png")
                    print("    Screenshot saved")

                    next_btn = active_page.locator("#identifierNext").first
                    if next_btn.count() > 0:
                        next_btn.click(timeout=30000)
                        print("    Clicked Next...")
                        time.sleep(5)
                        try:
                            active_page.wait_for_load_state("networkidle", timeout=15000)
                        except:
                            pass
                        print(f"    URL after Next: {active_page.url}")
                        active_page.screenshot(path="D:/done/tmp_stitch_login2.png")
                        print("    Final screenshot saved")
                else:
                    print("    No email input found")
                    active_page.screenshot(path="D:/done/tmp_stitch_login2.png")
            except Exception as e:
                print(f"    Error: {e}")
                active_page.screenshot(path="D:/done/tmp_stitch_login2.png")

        print("\n[DONE]")
        context.close()

if __name__ == "__main__":
    main()
