"""
SmartEX 列車検索のテストスクリプト

login()でログイン後、検索機能をテスト
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

from app.executors.ex_reservation.login import login, complete_otp_authentication, check_logged_in
from app.executors.ex_reservation.search import (
    open_search_form,
    fill_search_form,
    execute_search,
)
from app.utils.session_manager import SessionManager

# .envファイルを読み込み
load_dotenv()

# 認証情報を環境変数から取得
MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")

# ログファイル設定
LOG_FILE = "logs/search_test.log"


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
    print("SmartEX 列車検索テスト")
    print(f"ログファイル: {LOG_FILE}")
    print("=" * 60)
    print()

    if not MEMBER_ID or not PASSWORD:
        print("エラー: .envファイルに EX_MEMBER_ID と EX_PASSWORD を設定してください")
        tee.close()
        sys.stdout = tee.stdout
        return

    # セッションマネージャーを初期化
    session_mgr = SessionManager("smartex")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)

        # 既存セッションがあれば復元
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            print(f"会員ID: {MEMBER_ID}")
            print(f"パスワード: {'*' * len(PASSWORD)}\n")

            # Step 1: ログイン状態確認
            print("=" * 60)
            print("ログイン状態を確認中...")
            print("=" * 60)
            print()

            # SmartEXのマイページにアクセスして状態確認
            await page.goto("https://shinkansen2.jr-central.co.jp/RSV_P/p7A/ClientService", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # デバッグ: 現在のURLを確認
            current_url = page.url
            print(f"現在のURL: {current_url}")

            # デバッグ: ログアウトリンクの存在確認
            logout_count = await page.locator('link:has-text("ログアウト")').count()
            print(f"ログアウトリンク検出: {logout_count}件")

            is_logged_in = await check_logged_in(page)
            print(f"ログイン状態判定: {is_logged_in}\n")

            if is_logged_in:
                print("OK 既にログイン済みです（セッション復元成功）\n")
            else:
                print("未ログイン状態です。ログインします...\n")

                login_result = await login(page, MEMBER_ID, PASSWORD)

                # OTP必要な場合はOTP処理を実行
                if login_result.requires_otp:
                    print("\n" + "=" * 60)
                    print("OTP認証が必要です")
                    print("=" * 60)
                    print()

                    login_result = await complete_otp_authentication(
                        page=page,
                        otp_callback=get_otp_from_user,
                    )

                if not login_result.success:
                    print(f"NG ログイン失敗: {login_result.message}")
                    return

                print("OK ログイン成功\n")

                # ログイン成功後、セッションを保存
                await session_mgr.save_session(context)

            # Step 2: 検索フォームを開く
            print("=" * 60)
            print("検索フォームを開いています...")
            print("=" * 60)
            print()

            if not await open_search_form(page):
                print("NG 検索フォームを開けませんでした")
                return

            print("OK 検索フォームを開きました\n")

            # Step 3: 検索条件を入力
            print("=" * 60)
            print("検索条件を入力中...")
            print("=" * 60)
            print()

            # テストシナリオ: 新大阪から博多の1月25日の19時台に出発
            # 2人席で通路側を予約
            departure = "新大阪"
            arrival = "博 多"
            hour = "19時"
            minute = "00分"

            print(f"出発駅: {departure}")
            print(f"到着駅: {arrival}")
            print(f"日付: 2026年1月25日")
            print(f"時刻: {hour}{minute}")
            print(f"座席: 2人席・通路側希望\n")

            if not await fill_search_form(page, departure, arrival, hour, minute):
                print("NG 検索条件の入力に失敗しました")
                return

            print("OK 検索条件を入力しました\n")

            # Step 4: 検索実行
            print("=" * 60)
            print("列車を検索中...")
            print("=" * 60)
            print()

            search_result = await execute_search(page)

            if not search_result.success:
                print(f"NG 検索失敗: {search_result.message}")
                if search_result.screenshot_path:
                    print(f"スクリーンショット: {search_result.screenshot_path}")
                return

            print(f"OK {search_result.message}\n")

            # Step 5: 検索結果を表示
            print("=" * 60)
            print("検索結果")
            print("=" * 60)
            print()

            for i, train in enumerate(search_result.options):
                print(f"[{i + 1}] {train.train_name}")
                print(f"    発: {train.departure_time}")
                print(f"    着: {train.arrival_time}")
                if train.price:
                    print(f"    料金: ¥{train.price:,}")
                print(f"    空席: {'○' if train.available else '×'}")
                print()

            if search_result.screenshot_path:
                print(f"スクリーンショット: {search_result.screenshot_path}\n")

            print("=" * 60)
            print("ブラウザを30秒間保持します（確認用）")
            print("=" * 60)
            await page.wait_for_timeout(30000)

        except Exception as e:
            print(f"\nエラー: {e}")
            import traceback
            traceback.print_exc()

            # エラー時もスクリーンショット
            try:
                screenshot_path = "screenshots/ex_search_error.png"
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
