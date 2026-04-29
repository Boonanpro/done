from playwright.sync_api import sync_playwright
import time

USER_DATA = r"D:/done/.playwright-stitch"
EMAIL = "0aw325171@gmail.com"
PASSWORD = "Emoto589"

def find_frame(page):
    for f in page.frames:
        if "app-companion" in f.url:
            return f
    return None

def main():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            USER_DATA,
            headless=False,
            args=['--disable-blink-features=AutomationControlled'],
            viewport={"width": 1280, "height": 720},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        popup_holder = {"pg": None}
        def on_page(pg):
            print("NEW PAGE:", pg.url)
            popup_holder["pg"] = pg
        ctx.on("page", on_page)

        page.goto("https://stitch.withgoogle.com/", wait_until="networkidle")
        print("Opened:", page.url)
        time.sleep(5)

        frame = None
        for _ in range(20):
            frame = find_frame(page)
            if frame:
                try:
                    frame.wait_for_selector("#try-now-btn", timeout=2000, state="attached")
                    break
                except Exception:
                    pass
            time.sleep(1)

        if not frame:
            print("ERROR: iframe not found")
            page.screenshot(path="D:/done/tmp_stitch_logged_in.png")
            ctx.close()
            return

        # Click may open popup
        try:
            with page.context.expect_page(timeout=15000) as pinfo:
                frame.locator("#try-now-btn").first.click()
                print("Clicked try-now-btn")
            popup = pinfo.value
            print("Popup opened:", popup.url)
        except Exception as e:
            print("no popup captured:", e)
            popup = popup_holder["pg"]

        # Determine login target
        time.sleep(3)
        target = None
        for pg in ctx.pages:
            try:
                if "accounts.google.com" in pg.url:
                    target = pg
                    break
            except Exception:
                pass
        if not target and popup:
            target = popup
        if not target:
            target = page

        try:
            target.bring_to_front()
        except Exception:
            pass
        print("Login target:", target.url)

        # Email
        try:
            target.wait_for_selector('input[type="email"]', timeout=30000, state="visible")
            target.fill('input[type="email"]', EMAIL)
            time.sleep(0.5)
            # Click Next button
            try:
                target.locator('#identifierNext button, #identifierNext').first.click(timeout=3000)
            except Exception:
                target.keyboard.press("Enter")
            print("Email submitted")
        except Exception as e:
            print("email err:", e)

        # Password
        try:
            target.wait_for_selector('input[type="password"]', timeout=30000, state="visible")
            time.sleep(1.5)
            target.fill('input[type="password"]', PASSWORD)
            time.sleep(0.5)
            try:
                target.locator('#passwordNext button, #passwordNext').first.click(timeout=3000)
            except Exception:
                target.keyboard.press("Enter")
            print("Password submitted")
        except Exception as e:
            print("password err:", e)

        # 2FA wait
        print("Waiting up to 120s for phone approval...")
        start = time.time()
        success = False
        checked = False
        while time.time() - start < 120:
            time.sleep(2)
            try:
                cur = target.url
            except Exception:
                # page might be closed after popup completes
                cur = ""
                # fall back to main page
                try:
                    target = page
                    cur = target.url
                except Exception:
                    pass

            # Try to check "dont show again" checkbox
            if not checked:
                try:
                    cbs = target.locator('input[type="checkbox"]').all()
                    for cb in cbs:
                        try:
                            if cb.is_visible():
                                cb.check()
                                checked = True
                                print("Checked dont-show-again")
                                break
                        except Exception:
                            pass
                except Exception:
                    pass

            # Success conditions
            if "challenge" not in cur and "signin" not in cur and ("stitch" in cur or "appspot" in cur or cur == ""):
                # Check main page - login often redirects main stitch page
                try:
                    main_frame = find_frame(page)
                    if main_frame:
                        # Look for signed-in indicator - avatar or absence of try-now
                        has_btn = main_frame.locator("#try-now-btn").count() > 0
                        if not has_btn:
                            success = True
                            print("try-now-btn gone -> logged in")
                            break
                except Exception:
                    pass
                if "accounts.google.com" not in cur and cur:
                    success = True
                    print("Redirected off Google:", cur)
                    break

        time.sleep(3)
        # Screenshot whatever active page
        final_url = ""
        try:
            final_url = target.url
        except Exception:
            final_url = page.url
        try:
            target.screenshot(path="D:/done/tmp_stitch_logged_in.png")
        except Exception:
            try:
                page.screenshot(path="D:/done/tmp_stitch_logged_in.png")
            except Exception as e:
                print("screenshot err:", e)

        print(f"RESULT: success={success} final_url={final_url}")
        time.sleep(2)
        ctx.close()

if __name__ == "__main__":
    main()
