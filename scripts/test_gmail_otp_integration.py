"""
Gmail OTP統合テスト
EXログインとSafeKey認証にGmail OTP自動取得を統合
"""
import asyncio
import os
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from playwright.async_api import async_playwright
from app.executors.ex_reservation.login import login, complete_otp_authentication
from app.utils.gmail_otp_helper import get_sms_otp_from_gmail_async

load_dotenv()

EX_MEMBER_ID = os.getenv('EX_MEMBER_ID')
EX_PASSWORD = os.getenv('EX_PASSWORD')


async def gmail_otp_callback() -> str:
    """
    Gmail経由でSMS OTPを取得するコールバック関数

    EXログイン・SafeKey認証時に自動的に呼ばれる
    """
    print()
    print("=" * 70)
    print("Gmail経由でOTP取得中...")
    print("=" * 70)
    print()
    print("SMS Forwarder → Gmail → OTP抽出")
    print("待機中... (最大2分)")
    print()

    # 最大2分間待機してOTPを取得
    max_attempts = 24  # 24回 × 5秒 = 120秒

    for attempt in range(1, max_attempts + 1):
        print(f"[{attempt}/{max_attempts}] Gmailをチェック中...")

        # Gmail OTP取得を試行
        otp_code = await get_sms_otp_from_gmail_async(minutes=10)

        if otp_code:
            print()
            print("=" * 70)
            print(f"OTP取得成功: {otp_code}")
            print("=" * 70)
            print()
            return otp_code

        # 5秒待機して再試行
        if attempt < max_attempts:
            await asyncio.sleep(5)

    print()
    print("[ERROR] OTPが見つかりませんでした（タイムアウト）")
    print()

    # フォールバック: 手動入力
    print("手動でOTPを入力してください:")
    loop = asyncio.get_event_loop()
    otp_code = await loop.run_in_executor(
        None,
        lambda: input("OTP (6桁): ").strip()
    )
    return otp_code


async def test_ex_login_with_gmail_otp():
    """Gmail OTP統合でEXログインをテスト"""
    print()
    print("=" * 70)
    print("Gmail OTP統合テスト - EXログイン")
    print("=" * 70)
    print()

    if not EX_MEMBER_ID or not EX_PASSWORD:
        print("[ERROR] EX_MEMBER_ID and EX_PASSWORD must be set in .env")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # EXログイン
            print("EXにログイン中...")
            login_result = await login(
                page,
                member_id=EX_MEMBER_ID,
                password=EX_PASSWORD,
            )

            if login_result.requires_otp:
                print()
                print("=" * 70)
                print("OTP認証が必要です")
                print("=" * 70)
                print()

                # Gmail OTPコールバックでOTP認証を完了
                otp_result = await complete_otp_authentication(
                    page,
                    otp_callback=gmail_otp_callback
                )

                if otp_result.success:
                    print()
                    print("=" * 70)
                    print("[SUCCESS] Gmail OTP統合ログイン成功！")
                    print("=" * 70)
                    print()
                else:
                    print()
                    print("=" * 70)
                    print(f"[ERROR] ログイン失敗: {otp_result.message}")
                    print("=" * 70)
                    print()

            elif login_result.success:
                print()
                print("=" * 70)
                print("[SUCCESS] ログイン成功（OTP不要）")
                print("=" * 70)
                print()

            else:
                print()
                print("=" * 70)
                print(f"[ERROR] ログイン失敗: {login_result.message}")
                print("=" * 70)
                print()

            # 確認のため30秒待機
            print("ブラウザを30秒間保持します（確認用）...")
            await asyncio.sleep(30)

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(test_ex_login_with_gmail_otp())
