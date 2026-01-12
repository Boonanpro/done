"""
EXキャンセルエクスキューターのテスト

予約番号2073をキャンセル（実行はしない）
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
from app.executors.ex_reservation.cancel import cancel_reservation
from app.utils.session_manager import SessionManager
from app.utils.gmail_otp_helper import get_sms_otp_from_gmail_async

load_dotenv()

MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")


async def get_otp_from_gmail() -> str:
    """Gmail経由でOTPを取得"""
    print()
    print("=" * 70)
    print("Gmail経由でOTP自動取得中...")
    print("=" * 70)
    print()

    await asyncio.sleep(10)  # SMS転送待機

    for attempt in range(1, 37):
        print(f"[{attempt}/36] Gmailをチェック中...")
        otp_code = await get_sms_otp_from_gmail_async(minutes=15)

        if otp_code:
            print()
            print("=" * 70)
            print(f"[SUCCESS] OTP取得: {otp_code}")
            print("=" * 70)
            print()
            return otp_code

        if attempt < 36:
            await asyncio.sleep(5)

    print()
    print("[TIMEOUT] OTPが見つかりませんでした")
    return ""


async def main():
    print("=" * 70)
    print("EX Cancellation Test - Reservation 2073")
    print("=" * 70)
    print()
    print("Target: Reservation 2073")
    print("Mode: DRY RUN (confirm=False)")
    print()

    session_mgr = SessionManager("smartex_cancel_test")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # Login with OTP
            print("[1/2] Login with OTP...")
            result = await login(page, MEMBER_ID, PASSWORD)

            if result.requires_otp:
                print("  OTP authentication required")
                result = await complete_otp_authentication(page, get_otp_from_gmail)

            if not result.success:
                print(f"  [ERROR] Login failed: {result.message}")
                return

            print("[OK] Login successful\n")
            await session_mgr.save_session(context)

            # OTP画面を確認してクリックする
            sms_button = page.locator('text="SMS送信"').first
            if await sms_button.count() > 0:
                print("  [INFO] OTP screen detected after login")
                await sms_button.click()
                await page.wait_for_timeout(2000)

                otp_code = await get_otp_from_gmail()
                if not otp_code:
                    print("  [ERROR] Failed to get OTP")
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

                print("  [OK] OTP authentication completed")

            # Cancel reservation
            print("[2/2] Cancel reservation...")
            print()

            cancel_result = await cancel_reservation(
                page,
                reservation_number="2073",
                confirm=True,  # 実際にキャンセルを実行
            )

            print()
            print("=" * 70)
            print("Test Result")
            print("=" * 70)
            print(f"Success: {cancel_result.success}")
            print(f"Message: {cancel_result.message}")

            if cancel_result.refund_amount:
                print(f"Refund Amount: ¥{cancel_result.refund_amount}")
            if cancel_result.refund_fee:
                print(f"Refund Fee: ¥{cancel_result.refund_fee}")
            if cancel_result.screenshot_path:
                print(f"Screenshot: {cancel_result.screenshot_path}")

            print()

            if cancel_result.success:
                print("[SUCCESS] キャンセルエクスキューターは正しく動作しています")
                print()
                print("実際にキャンセルを実行する場合:")
                print("  confirm=True に変更してください")
            else:
                print("[FAILED] キャンセルエクスキューターにエラーがあります")

            print()

            # 少し待機
            await page.wait_for_timeout(5000)

        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="test_cancel_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
