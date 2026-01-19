"""
EXキャンセルフローの自動調査

予約番号2073のキャンセル手順を自動で確認し、セレクタを記録
"""
import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime

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
    print("  Gmail経由でOTP取得中...")
    await asyncio.sleep(10)  # SMS転送待機

    for attempt in range(1, 25):
        print(f"  [{attempt}/24] Gmailをチェック中...")
        otp_code = await get_sms_otp_from_gmail_async(minutes=10)
        if otp_code:
            print(f"  [OK] OTP取得: {otp_code}")
            return otp_code
        await asyncio.sleep(5)

    print("  [TIMEOUT] OTPが見つかりませんでした")
    return ""


async def main():
    print("=" * 70)
    print("EX Cancellation Flow Auto Investigation")
    print("=" * 70)
    print()
    print("Target: Reservation 2073")
    print()

    session_mgr = SessionManager("smartex_cancel_auto")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # Login with OTP
            print("[1] Login with OTP...")
            result = await login(page, MEMBER_ID, PASSWORD)

            if result.requires_otp:
                print("  OTP authentication required")
                result = await complete_otp_authentication(page, get_otp_from_gmail)

            if not result.success:
                print(f"Login failed: {result.message}")
                return

            print("[OK] Login successful\n")
            await session_mgr.save_session(context)

            # マイページに移動
            print("[2] Navigate to My Page...")
            await page.wait_for_timeout(2000)
            current_url = page.url
            print(f"  Current URL: {current_url}")

            # スクリーンショット
            await page.screenshot(path="ex_cancel_01_mypage.png")
            html = await page.content()
            with open("ex_cancel_01_mypage.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("  Screenshot: ex_cancel_01_mypage.png")
            print("  HTML saved: ex_cancel_01_mypage.html")
            print()

            # 予約確認ボタンを探す
            print("[3] Looking for reservation button...")

            # 「予約確認・変更・払戻」を探す
            possible_selectors = [
                'text="予約確認・変更・払戻"',
                'text="予約確認"',
                'text="予約の確認"',
                'a:has-text("予約")',
            ]

            reservation_button = None
            for selector in possible_selectors:
                count = await page.locator(selector).count()
                if count > 0:
                    print(f"  Found: {selector} ({count} elements)")
                    reservation_button = page.locator(selector).first
                    break

            if not reservation_button:
                print("  [ERROR] Reservation button not found")
                return

            # 予約確認ページに移動
            print("[4] Click reservation button...")
            await reservation_button.click()
            await page.wait_for_timeout(3000)

            # 予約一覧を記録
            await page.screenshot(path="ex_cancel_02_reservation_list.png")
            html = await page.content()
            with open("ex_cancel_02_reservation_list.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("  Screenshot: ex_cancel_02_reservation_list.png")
            print("  HTML saved: ex_cancel_02_reservation_list.html")
            print()

            # 予約番号2073を探す
            print("[5] Looking for reservation 2073...")
            reservation_link = page.locator('text="2073"').first
            if await reservation_link.count() > 0:
                print("  Found reservation 2073")

                # 予約詳細に移動
                print("[6] Click reservation 2073...")
                await reservation_link.click()
                await page.wait_for_timeout(3000)

                # 予約詳細を記録
                await page.screenshot(path="ex_cancel_03_detail.png")
                html = await page.content()
                with open("ex_cancel_03_detail.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("  Screenshot: ex_cancel_03_detail.png")
                print("  HTML saved: ex_cancel_03_detail.html")
                print()

                # キャンセル/払戻ボタンを探す
                print("[7] Looking for cancel/refund buttons...")

                cancel_texts = [
                    "払戻",
                    "払い戻し",
                    "キャンセル",
                    "取消",
                ]

                for text in cancel_texts:
                    elements = await page.locator(f'text="{text}"').all()
                    if elements:
                        print(f"  Found '{text}': {len(elements)} elements")
                        for i, elem in enumerate(elements[:3]):
                            try:
                                tag = await elem.evaluate("el => el.tagName")
                                elem_id = await elem.evaluate("el => el.id || ''")
                                elem_class = await elem.evaluate("el => el.className || ''")
                                elem_text = await elem.text_content()
                                print(f"    [{i}] <{tag}> id='{elem_id}' class='{elem_class}' text='{elem_text.strip()}'")
                            except:
                                pass

                # 全てのボタンとリンクを表示
                print()
                print("  All buttons and links on this page:")
                buttons = await page.locator('button, a, input[type="button"], input[type="submit"]').all()
                for i, btn in enumerate(buttons[:15]):
                    try:
                        text = await btn.text_content()
                        tag = await btn.evaluate("el => el.tagName")
                        btn_id = await btn.evaluate("el => el.id || ''")
                        if text and text.strip():
                            print(f"    [{i}] <{tag}> id='{btn_id}' text='{text.strip()[:40]}'")
                    except:
                        pass

                print()
                print("[INFO] Investigation complete. Check HTML files for selectors.")
                print("[WARNING] NOT clicking cancel button to preserve the reservation.")

            else:
                print("  [ERROR] Reservation 2073 not found")

            # 最後に少し待機
            await page.wait_for_timeout(5000)

        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="ex_cancel_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
