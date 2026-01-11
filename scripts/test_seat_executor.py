"""
座席選択エクスキューター動作確認スクリプト

検索 → 列車選択 → 座席選択 → 確認画面まで完全なフローをテスト
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
from app.executors.ex_reservation.search import (
    open_search_form,
    fill_search_form,
    execute_search,
    select_train,
)
from app.executors.ex_reservation.seat import complete_seat_selection
from app.utils.session_manager import SessionManager

load_dotenv()

MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")


async def get_otp_from_user() -> str:
    """OTP取得"""
    loop = asyncio.get_event_loop()
    otp_code = await loop.run_in_executor(
        None,
        lambda: input("\nOTPコード（6桁）を入力してください: ").strip()
    )
    return otp_code


async def main():
    print("=" * 70)
    print("座席選択エクスキューター 動作確認")
    print("検索 → 列車選択 → 座席選択 → 確認画面")
    print("=" * 70)
    print()

    session_mgr = SessionManager("smartex_seat_test")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # ログイン
            print("🔐 ログイン中...")
            result = await login(page, MEMBER_ID, PASSWORD)

            if result.requires_otp:
                print("\n📞 OTP認証が必要です")
                result = await complete_otp_authentication(page, get_otp_from_user)

            if not result.success:
                print(f"❌ ログイン失敗: {result.message}")
                return

            print("✓ ログイン成功\n")
            await session_mgr.save_session(context)

            # 検索フォームを開く
            print("🔍 検索フォームを開く...")
            if not await open_search_form(page):
                print("❌ 検索フォームを開けませんでした")
                return
            print("✓ 検索フォーム表示\n")

            # 検索条件を入力
            print("📝 検索条件入力: 新大阪 → 博多 19時")
            if not await fill_search_form(
                page,
                departure_station="新大阪",
                arrival_station="博多",
                hour="19時",
                adult_count=1,
            ):
                print("❌ 検索条件の入力に失敗しました")
                return
            print("✓ 検索条件入力完了\n")

            # 検索実行
            print("🚄 検索実行中...")
            search_result = await execute_search(page)

            if not search_result.success:
                print(f"❌ 検索失敗: {search_result.message}")
                if search_result.screenshot_path:
                    print(f"スクリーンショット: {search_result.screenshot_path}")
                return

            print(f"✓ {search_result.message}")
            if search_result.options:
                print("\n列車候補:")
                for option in search_result.options[:3]:  # 最初の3件を表示
                    status = "○" if option.available else "×"
                    print(f"  [{option.index}] {option.train_name}")
                    print(f"      {option.departure_time}発 → {option.arrival_time}着 (空席: {status})")
            print()

            # 最初の列車を選択
            print("🎫 最初の列車を選択...")
            if not await select_train(page, index=0):
                print("❌ 列車選択に失敗しました")
                return
            print("✓ 列車選択完了\n")

            # 座席選択
            print("💺 座席選択中...")
            print("  商品: 最初の商品（通常は最安値のスマートEX）")
            print("  座席位置: 通路側C")
            seat_result = await complete_seat_selection(
                page,
                product_index=0,  # 最初の商品（通常は最安値）
                seat_position="通路側C",  # 通路側を希望
            )

            if not seat_result.success:
                print(f"❌ 座席選択失敗: {seat_result.message}")
                if seat_result.screenshot_path:
                    print(f"スクリーンショット: {seat_result.screenshot_path}")
                return

            print(f"✓ {seat_result.message}")
            if seat_result.screenshot_path:
                print(f"スクリーンショット: {seat_result.screenshot_path}")
            print()

            print("=" * 70)
            print("✅ 座席選択エクスキューター 動作確認完了")
            print("=" * 70)
            print()
            print("確認画面まで到達しました。")
            print("次のステップ: 確認画面の情報を解析して購入エクスキューターを実装")
            print()

            input("\nEnterキーを押すとブラウザを閉じます...")

        except Exception as e:
            print(f"\n❌ エラー: {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="test_seat_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
