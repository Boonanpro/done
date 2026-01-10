"""
SmartEX OTPログインのテストスクリプト（統合版）

login_with_auto_otp()を使用した自動OTP判定テスト
"""
import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime

# プロジェクトルートをPATHに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from dotenv import load_dotenv

from app.executors.ex_reservation.selectors import URLS, COMMON
from app.executors.ex_reservation.login import login, complete_otp_authentication

# .envファイルを読み込み
load_dotenv()

# 認証情報を環境変数から取得
MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")

# ログファイル設定
LOG_FILE = "logs/otp_test.log"


class TeeOutput:
    """標準出力とファイルの両方に出力するクラス"""
    def __init__(self, file_path):
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        self.file = open(file_path, 'w', encoding='utf-8')
        self.stdout = sys.stdout

    def write(self, message):
        self.stdout.write(message)
        self.file.write(message)
        self.file.flush()

    def flush(self):
        self.stdout.flush()
        self.file.flush()

    def close(self):
        self.file.close()


async def get_otp_from_user() -> str:
    """
    ユーザーからOTPを取得するコールバック関数

    ブラウザ上で「自動音声案内発信」ボタンがクリックされた後、
    ユーザーの電話に届いたOTPをターミナルで入力してもらう
    """
    print("\n" + "=" * 60)
    print("電話にOTPが届いているはずです")
    print("=" * 60)

    # 非同期でユーザー入力を待つ
    loop = asyncio.get_event_loop()
    otp_code = await loop.run_in_executor(
        None,
        lambda: input("\nOTPコード（6桁）を入力してください: ").strip()
    )

    return otp_code


async def main():
    # ログファイルへの出力を設定
    tee = TeeOutput(LOG_FILE)
    sys.stdout = tee

    print("=" * 60)
    print("SmartEX OTPログインテスト（統合版）")
    print(f"ログファイル: {LOG_FILE}")
    print("=" * 60)
    print()

    if not MEMBER_ID or not PASSWORD:
        print("エラー: .envファイルに EX_MEMBER_ID と EX_PASSWORD を設定してください")
        tee.close()
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="ja-JP",
        )
        page = await context.new_page()

        try:
            print(f"会員ID: {MEMBER_ID}")
            print(f"パスワード: {'*' * len(PASSWORD)}\n")

            print("=" * 60)
            print("ログイン処理を開始します")
            print("=" * 60)
            print()

            # Step 1: 通常のログインを試みる
            result = await login(
                page=page,
                member_id=MEMBER_ID,
                password=PASSWORD,
            )

            # Step 2: OTP必要な場合はOTP処理を実行
            if result.requires_otp:
                print("\n" + "=" * 60)
                print("OTP認証が必要です")
                print("=" * 60)
                print()

                result = await complete_otp_authentication(
                    page=page,
                    otp_callback=get_otp_from_user,  # OTP取得コールバック
                )

            print("\n" + "=" * 60)
            print("ログイン結果")
            print("=" * 60)
            print(f"成功: {result.success}")
            print(f"メッセージ: {result.message}")
            print(f"ページ状態: {result.page_state.value}")
            print()

            if result.success:
                print("OK ログイン成功！")

                # ログイン後のページを確認
                current_url = page.url
                print(f"現在のURL: {current_url}")

                # マイページの要素を確認
                is_logged_in = await page.locator(COMMON["logged_in"]).count() > 0
                print(f"ログイン状態確認: {is_logged_in}")

                # スクリーンショット保存
                screenshot_path = "screenshots/ex_otp_success.png"
                os.makedirs("screenshots", exist_ok=True)
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"スクリーンショット保存: {screenshot_path}")

            else:
                print(f"NG ログイン失敗: {result.message}")

                # エラー時のスクリーンショット
                screenshot_path = "screenshots/ex_otp_failure.png"
                os.makedirs("screenshots", exist_ok=True)
                await page.screenshot(path=screenshot_path)
                print(f"エラー画面保存: {screenshot_path}")

            print("\n" + "=" * 60)
            print("ブラウザを30秒間保持します（確認用）")
            print("=" * 60)
            await page.wait_for_timeout(30000)

        except Exception as e:
            print(f"\nエラー: {e}")
            import traceback
            traceback.print_exc()

            # エラー時もスクリーンショット
            try:
                screenshot_path = "screenshots/ex_otp_error.png"
                os.makedirs("screenshots", exist_ok=True)
                await page.screenshot(path=screenshot_path)
                print(f"エラー画面保存: {screenshot_path}")
            except Exception:
                pass

        finally:
            await browser.close()
            tee.close()
            sys.stdout = tee.stdout  # 標準出力を元に戻す


if __name__ == "__main__":
    asyncio.run(main())
