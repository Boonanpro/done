"""
複数人予約テストスクリプト（席が離れてもOK版）

2人分の予約で「席が離れても良い」オプションをテスト
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
    print("複数人予約テスト（2人・席が離れてもOK）")
    print("=" * 70)
    print()

    session_mgr = SessionManager("smartex_multi_separate_test")

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

            # 検索
            await open_search_form(page)
            print("📝 検索条件入力: 新大阪 → 博多 19時 【大人2名】")
            await fill_search_form(page, "新大阪", "博多", "19時", adult_count=2)
            print("✓ 検索条件入力完了（大人2名）\n")

            search_result = await execute_search(page)
            if not search_result.success:
                print(f"❌ 検索失敗: {search_result.message}")
                return
            print(f"✓ {search_result.message}\n")

            # 列車選択
            await select_train(page, 0)

            # ★★★ 座席選択（席が離れても良い） ★★★
            print("💺 座席選択中（2人分・席が離れてもOK）...")
            print("  商品: 最初の商品")
            print("  座席位置: 指定なし")
            print("  席が離れても良い: True ★")

            seat_result = await complete_seat_selection(
                page,
                product_index=0,
                seat_position="指定なし",
                allow_separate_seats=True,  # ★ 席が離れてもOK
            )

            if not seat_result.success:
                print(f"❌ 座席選択失敗: {seat_result.message}")
                return

            print(f"✓ {seat_result.message}")
            print(f"スクリーンショット: {seat_result.screenshot_path}\n")

            print("=" * 70)
            print("✅ 複数人予約テスト完了（席が離れてもOK）")
            print("=" * 70)
            print()
            print("確認画面で以下を確認してください:")
            print("  - 大人2名分の予約になっているか")
            print("  - 席が離れていても予約できているか")
            print()

            input("\nEnterキーを押すとブラウザを閉じます...")

        except Exception as e:
            print(f"\n❌ エラー: {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="test_multi_separate_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
