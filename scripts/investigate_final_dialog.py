"""
払戻実行ボタンクリック後のダイアログを調査
"""
import asyncio
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from dotenv import load_dotenv
from app.executors.ex_reservation.login import login, complete_otp_authentication
from app.utils.session_manager import SessionManager
from app.utils.gmail_otp_helper import get_sms_otp_from_gmail_async

load_dotenv()

MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")


async def get_otp_from_gmail() -> str:
    """Gmail経由でOTPを取得"""
    print("Gmail経由でOTP自動取得中...")
    await asyncio.sleep(10)

    for attempt in range(1, 37):
        print(f"[{attempt}/36] Gmailをチェック中...")
        otp_code = await get_sms_otp_from_gmail_async(minutes=15)

        if otp_code:
            print(f"[SUCCESS] OTP取得: {otp_code}")
            return otp_code

        if attempt < 36:
            await asyncio.sleep(5)

    print("[TIMEOUT] OTPが見つかりませんでした")
    return ""


async def main():
    session_mgr = SessionManager("smartex_cancel_test")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # Login
            print("[1/3] Login with OTP...")
            result = await login(page, MEMBER_ID, PASSWORD)

            if result.requires_otp:
                result = await complete_otp_authentication(page, get_otp_from_gmail)

            if not result.success:
                print(f"[ERROR] Login failed: {result.message}")
                return

            print("[OK] Login successful\n")
            await session_mgr.save_session(context)

            # OTP画面をクリア
            sms_button = page.locator('text="SMS送信"').first
            if await sms_button.count() > 0:
                print("[INFO] OTP screen detected after login")
                await sms_button.click()
                await page.wait_for_timeout(2000)

                otp_code = await get_otp_from_gmail()
                if not otp_code:
                    print("[ERROR] Failed to get OTP")
                    return

                otp_input = page.locator('input[type="tel"]').first
                await otp_input.fill(otp_code)
                await page.wait_for_timeout(1000)

                close_dialog = page.locator('text="閉じる"').first
                if await close_dialog.count() > 0:
                    await close_dialog.click()
                    await page.wait_for_timeout(1000)

                ok_button = page.locator('input[type="submit"][name="b2"]').first
                await ok_button.click()
                await page.wait_for_timeout(3000)

                print("[OK] OTP authentication completed\n")

            # Navigate to cancellation confirmation screen
            print("[2/3] Navigate to confirmation screen...")

            # Menu
            menu_button = page.locator('button:has-text("メニュー")').first
            if await menu_button.count() > 0:
                await menu_button.click()
                await page.wait_for_timeout(2000)

            # Reservation link
            reservation_link = page.locator('a:has-text("確認")').first
            await reservation_link.click()
            await page.wait_for_timeout(3000)

            # Refund button
            refund_button = page.locator('input[type="submit"][value*="払戻"]').first
            await refund_button.click(force=True)
            await page.wait_for_timeout(3000)

            # Dialog OK
            dialog_ok = page.locator('text="OK 確認画面へ"').first
            if await dialog_ok.count() > 0:
                await dialog_ok.click()
                await page.wait_for_timeout(3000)

            print("[OK] Reached confirmation screen\n")

            # Save HTML before clicking
            html_before = await page.content()
            with open("dialog_before_click.html", "w", encoding="utf-8") as f:
                f.write(html_before)
            print("[SAVED] dialog_before_click.html")

            # Click execute button
            print("[3/3] Click execute button and investigate dialog...")
            execute_button = page.locator('input[name="b2"][type="submit"]').first
            await execute_button.click(force=True)
            await page.wait_for_timeout(3000)

            # Save HTML after clicking
            html_after = await page.content()
            with open("dialog_after_click.html", "w", encoding="utf-8") as f:
                f.write(html_after)
            print("[SAVED] dialog_after_click.html")

            # Search for dialog elements
            print("\n=== Dialog Investigation ===")

            dialog_selectors = [
                'div[class*="dialog"]',
                'div[class*="modal"]',
                'div[class*="popup"]',
                'div[class*="LBX"]',
                'div[id*="dialog"]',
                'div[id*="modal"]',
                'text="OK"',
                'button:has-text("OK")',
                'input[type="button"][value="OK"]',
                'a:has-text("OK")',
            ]

            for selector in dialog_selectors:
                elements = page.locator(selector)
                count = await elements.count()
                if count > 0:
                    print(f"{selector}: {count} elements found")

                    for i in range(min(count, 3)):
                        elem = elements.nth(i)
                        try:
                            text = await elem.text_content()
                            if text and text.strip():
                                print(f"  [{i}] {text.strip()[:100]}")
                        except:
                            pass

            # Screenshot
            await page.screenshot(path="dialog_investigation.png")
            print("\n[SAVED] dialog_investigation.png")

            # Wait for manual inspection
            print("\n待機中... (60秒)")
            await page.wait_for_timeout(60000)

        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="dialog_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
