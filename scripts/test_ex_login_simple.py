"""
EXログインエクスキューターのテスト

Gmail経由でOTP認証を含むログインをテスト
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
    print("EX Login Test with OTP Authentication")
    print("=" * 70)
    print()

    session_mgr = SessionManager("ex_login_test")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # Step 1: Login
            print("[1/2] ログイン中...")
            result = await login(page, MEMBER_ID, PASSWORD)

            if result.requires_otp:
                print("[INFO] OTP認証が必要です")
                print()

                # Step 2: OTP Authentication
                print("[2/2] OTP認証中...")
                result = await complete_otp_authentication(page, get_otp_from_gmail)

                if not result.success:
                    print(f"[ERROR] OTP認証失敗: {result.message}")
                    return

                print("[OK] OTP認証成功")
            elif not result.success:
                print(f"[ERROR] ログイン失敗: {result.message}")
                return
            else:
                print("[OK] OTP認証は不要でした")

            print()
            print("=" * 70)
            print("ログイン成功！")
            print("=" * 70)
            print(f"メッセージ: {result.message}")
            print()

            # セッションを保存
            await session_mgr.save_session(context)
            print("[INFO] セッションを保存しました")

            # 少し待機して画面を確認
            print()
            print("ログイン後の画面を確認中... (10秒)")
            await page.wait_for_timeout(10000)

            # スクリーンショット
            screenshot_path = "ex_login_success.png"
            await page.screenshot(path=screenshot_path)
            print(f"[INFO] スクリーンショット保存: {screenshot_path}")

        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="ex_login_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
