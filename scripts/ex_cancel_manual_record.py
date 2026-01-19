"""
EX Cancellation Flow Manual Recording Script

Opens browser with manual waits at each step for investigation
"""
import asyncio
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from dotenv import load_dotenv
from app.executors.ex_reservation.login import login
from app.utils.session_manager import SessionManager

load_dotenv()

MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")


async def save_page_state(page, step_name):
    """Save page state"""
    screenshot_path = f"ex_cancel_{step_name}.png"
    html_path = f"ex_cancel_{step_name}.html"

    await page.screenshot(path=screenshot_path)
    html = await page.content()
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  [Screenshot] {screenshot_path}")
    print(f"  [HTML] {html_path}")

    return screenshot_path, html_path


async def main():
    print("=" * 70)
    print("EX Cancellation Flow - Manual Recording")
    print("=" * 70)
    print()
    print("This script waits 30 seconds at each step.")
    print("Please operate manually during the wait time.")
    print()

    session_mgr = SessionManager("smartex_manual_cancel")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=1000,
        )
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # Login
            print("[Step 1] Logging in...")
            result = await login(page, MEMBER_ID, PASSWORD)

            if not result.success:
                print(f"  [ERROR] Login failed: {result.message}")
                return

            print("  [OK] Login successful")
            await session_mgr.save_session(context)
            await save_page_state(page, "step1_logged_in")
            print()

            # Step 2: Navigate to reservation menu
            print("[Step 2] Navigate to reservation menu")
            print("  Please click 'Menu' button and select reservation option")
            print("  [WAIT] 30 seconds...")
            await page.wait_for_timeout(30000)
            await save_page_state(page, "step2_menu_clicked")
            print()

            # Step 3: Reservation list
            print("[Step 3] Reservation list displayed")
            print("  Please find and click reservation 2073")
            print("  [WAIT] 30 seconds...")

            # Search for reservation 2073
            reservations = await page.locator('text="2073"').all()
            print(f"  [INFO] Elements containing '2073': {len(reservations)}")

            await page.wait_for_timeout(30000)
            await save_page_state(page, "step3_reservation_list")
            print()

            # Step 4: Reservation detail
            print("[Step 4] Reservation detail displayed")
            print("  Please find cancel/refund button (DO NOT click yet)")
            print("  [WAIT] 30 seconds...")

            # Search for cancel button
            print("  [SEARCH] Looking for cancel/refund buttons...")
            cancel_keywords = ["払戻", "払い戻し", "キャンセル", "取消"]

            for keyword in cancel_keywords:
                elements = await page.locator(f'text="{keyword}"').all()
                if elements:
                    print(f"     '{keyword}': {len(elements)} elements")
                    for i, elem in enumerate(elements[:2]):
                        try:
                            tag = await elem.evaluate("el => el.tagName")
                            elem_id = await elem.evaluate("el => el.id || ''")
                            elem_class = await elem.evaluate("el => el.className || ''")
                            elem_text = await elem.text_content()
                            onclick = await elem.evaluate("el => el.onclick ? 'has onclick' : ''")
                            print(f"       [{i}] <{tag}> id='{elem_id}' class='{elem_class[:30]}' onclick='{onclick}'")
                            print(f"           text='{elem_text.strip()[:50]}'")
                        except:
                            pass

            await page.wait_for_timeout(30000)
            await save_page_state(page, "step4_detail")
            print()

            # Step 5: Cancel confirmation page
            print("[Step 5] Click the refund button")
            print("  [WAIT] 30 seconds...")
            await page.wait_for_timeout(30000)
            await save_page_state(page, "step5_cancel_confirm")
            print()

            # Step 6: Analyze confirmation page
            print("[Step 6] Analyzing cancel confirmation page...")
            print("  [SEARCH] Looking for confirmation/execute buttons...")

            confirm_keywords = ["実行", "確認", "はい", "払戻を実行", "キャンセルを実行"]

            for keyword in confirm_keywords:
                elements = await page.locator(f'text="{keyword}"').all()
                if elements:
                    print(f"     '{keyword}': {len(elements)} elements")
                    for i, elem in enumerate(elements[:2]):
                        try:
                            tag = await elem.evaluate("el => el.tagName")
                            elem_id = await elem.evaluate("el => el.id || ''")
                            elem_class = await elem.evaluate("el => el.className || ''")
                            elem_text = await elem.text_content()
                            print(f"       [{i}] <{tag}> id='{elem_id}' class='{elem_class[:30]}'")
                            print(f"           text='{elem_text.strip()[:50]}'")
                        except:
                            pass

            print()
            print("  [WARNING] DO NOT execute actual cancellation!")
            print("  [WAIT] 60 seconds before finishing...")
            await page.wait_for_timeout(60000)
            print()

            print("=" * 70)
            print("Investigation complete!")
            print("=" * 70)
            print()
            print("Saved files:")
            print("  - ex_cancel_step*.png")
            print("  - ex_cancel_step*.html")
            print()

        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="ex_cancel_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
