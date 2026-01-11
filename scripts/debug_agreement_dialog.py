"""
同意事項ダイアログのデバッグスクリプト
座席選択後のHTMLを保存してダイアログ構造を確認
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
from app.executors.ex_reservation.seat import select_product, select_seat_position
from app.executors.ex_reservation.selectors_complete import SEAT_SELECTION, AGREEMENT_DIALOG
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
    print("同意事項ダイアログ デバッグ")
    print("=" * 70)
    print()

    session_mgr = SessionManager("smartex_debug")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # ログイン
            print("ログイン中...")
            result = await login(page, MEMBER_ID, PASSWORD)

            if result.requires_otp:
                print("\nOTP認証が必要です")
                result = await complete_otp_authentication(page, get_otp_from_user)

            if not result.success:
                print(f"ログイン失敗: {result.message}")
                return

            print("✓ ログイン成功\n")
            await session_mgr.save_session(context)

            # 検索
            await open_search_form(page)
            await fill_search_form(page, "新大阪", "博多", "19時", 1)
            search_result = await execute_search(page)
            if not search_result.success:
                print(f"検索失敗: {search_result.message}")
                return

            # 列車選択
            await select_train(page, 0)

            # 商品選択
            print("\n商品を選択...")
            await select_product(page, 0)
            await page.wait_for_timeout(2000)

            # 座席位置選択
            print("座席位置を選択...")
            await select_seat_position(page, "通路側C")
            await page.wait_for_timeout(2000)

            # スクリーンショット
            await page.screenshot(path="debug_before_continue.png")
            print("スクリーンショット: debug_before_continue.png")

            # 予約を続けるボタンをクリック
            print("\n「予約を続ける」ボタンをクリック...")
            continue_btn = page.locator(SEAT_SELECTION["continue_button"])
            if await continue_btn.count() > 0:
                await continue_btn.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(3000)
                print("✓ クリック完了")

            # ここでHTMLとスクリーンショットを保存
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

            await page.screenshot(path=f"debug_after_continue_{timestamp}.png")
            print(f"\nスクリーンショット: debug_after_continue_{timestamp}.png")

            html = await page.content()
            html_path = f"debug_after_continue_{timestamp}.html"
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f"HTML保存: {html_path}")

            # ダイアログの存在確認
            print("\n=== ダイアログ検出テスト ===")

            # パターン1: .popup_wrap
            popup_wrap = page.locator('.popup_wrap')
            count = await popup_wrap.count()
            print(f"1. .popup_wrap の数: {count}")
            if count > 0:
                is_visible = await popup_wrap.is_visible()
                print(f"   visible: {is_visible}")

            # パターン2: h1:has-text("同意事項")
            heading = page.locator('h1:has-text("同意事項")')
            count = await heading.count()
            print(f"2. h1:has-text('同意事項') の数: {count}")
            if count > 0:
                is_visible = await heading.is_visible()
                print(f"   visible: {is_visible}")

            # パターン3: チェックボックス #chkbox_2
            checkbox = page.locator('#chkbox_2')
            count = await checkbox.count()
            print(f"3. #chkbox_2 の数: {count}")
            if count > 0:
                is_visible = await checkbox.is_visible()
                is_checked = await checkbox.is_checked()
                print(f"   visible: {is_visible}, checked: {is_checked}")

            # パターン4: すべてのチェックボックス
            all_checkboxes = await page.locator('input[type="checkbox"]').all()
            print(f"4. すべてのチェックボックス: {len(all_checkboxes)}個")

            # パターン5: 同意するラベル
            agree_label = page.locator('label:has-text("同意する")')
            count = await agree_label.count()
            print(f"5. label:has-text('同意する') の数: {count}")

            print("\n" + "=" * 70)
            input("\nEnterキーを押すとブラウザを閉じます...")

        except Exception as e:
            print(f"\nエラー: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
