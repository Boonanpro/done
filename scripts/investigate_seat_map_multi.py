"""
複数人予約時の座席表選択画面調査スクリプト

「座席表から指定する」を押した後の画面を調査
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
from app.executors.ex_reservation.search import (
    open_search_form,
    fill_search_form,
    execute_search,
    select_train,
)
from app.executors.ex_reservation.seat import select_product
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


async def save_page_info(page, name: str):
    """ページ情報を保存"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

    # スクリーンショット
    screenshot_path = f"seatmap_{name}_{timestamp}.png"
    await page.screenshot(path=screenshot_path, full_page=True)
    print(f"  📸 {screenshot_path}")

    # HTML保存
    html = await page.content()
    html_path = f"seatmap_{name}_{timestamp}.html"
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  📄 {html_path}")


async def main():
    print("=" * 70)
    print("座席表選択画面調査（2人分）")
    print("=" * 70)
    print()

    session_mgr = SessionManager("smartex_seatmap")

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

            # 検索（2人分）
            await open_search_form(page)
            print("📝 検索条件入力: 新大阪 → 博多 19時 【2人】")
            await fill_search_form(page, "新大阪", "博多", "19時", adult_count=2)

            search_result = await execute_search(page)
            if not search_result.success:
                print(f"❌ 検索失敗: {search_result.message}")
                return

            # 列車選択
            await select_train(page, 0)

            # 商品選択
            print("\n💺 商品を選択...")
            await select_product(page, 0)
            await page.wait_for_timeout(2000)
            print("✓ 商品選択完了\n")

            # === 座席表から指定するボタンをクリック ===
            print("=" * 70)
            print("座席表選択画面の調査")
            print("=" * 70)
            print()

            print("🗺️  「座席表から指定する」ボタンをクリック...")
            seat_map_btn = page.locator('button.seat_map_button')
            if await seat_map_btn.count() > 0:
                await seat_map_btn.click()
                await page.wait_for_timeout(3000)
                print("✓ クリック完了\n")

                # 座席表画面を保存
                print("📋 座席表画面の状態")
                await save_page_info(page, "01_seat_map")
                print()

                # 座席表の構造を調査
                print("🔍 座席表の構造を調査...")

                # 座席ボタンを探す
                seat_buttons = await page.locator('button[class*="seat"], .seat, td[class*="seat"]').all()
                print(f"   座席関連要素数: {len(seat_buttons)}")

                # 号車選択
                car_selects = await page.locator('select').all()
                print(f"   セレクトボックス数: {len(car_selects)}")

                # クリック可能な座席
                clickable_seats = await page.locator('button:not([disabled]), td.clickable, .seat-available').all()
                print(f"   クリック可能な座席数: {len(clickable_seats)}")

                print()

            else:
                print("❌ 座席表ボタンが見つかりません")

            print("=" * 70)
            print("調査完了")
            print("=" * 70)
            print()
            print("保存されたファイル:")
            print("  - seatmap_01_seat_map_*.png/html : 座席表画面")
            print()

            input("\nEnterキーを押すとブラウザを閉じます...")

        except Exception as e:
            print(f"\n❌ エラー: {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="investigate_seatmap_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
