"""
座席指定コントロールの詳細調査スクリプト

座席選択画面で商品を選択後に表示される:
- 座席指定：指定なし ボタン
- 座席表から指定する ボタン
- A/B/C/D/E 座席位置セレクタ

これらの動的要素のセレクタを取得する
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
from app.executors.ex_reservation.selectors_complete import SEAT_SELECTION
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


async def save_page_state(page, prefix: str):
    """ページの状態を保存"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    screenshot_path = f"{prefix}_{timestamp}.png"
    html_path = f"{prefix}_{timestamp}.html"

    await page.screenshot(path=screenshot_path)
    html = await page.content()
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"  📸 {screenshot_path}")
    print(f"  📄 {html_path}")


async def main():
    print("=" * 70)
    print("座席指定コントロール 詳細調査")
    print("=" * 70)
    print()

    session_mgr = SessionManager("smartex_seat_investigation")

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
                return

            print(f"✓ {search_result.message}\n")

            # 最初の列車を選択
            print("🎫 最初の列車を選択...")
            if not await select_train(page, index=0):
                print("❌ 列車選択に失敗しました")
                return
            print("✓ 列車選択完了\n")

            # === ここから座席選択画面の詳細調査 ===

            print("=" * 70)
            print("座席選択画面の調査開始")
            print("=" * 70)
            print()

            # 初期状態を保存
            print("📋 ステップ1: 商品選択前の初期状態")
            await save_page_state(page, "seat_01_initial")
            print()

            input("Enterキーを押すと商品（普通車）を選択します...")

            # 普通車タブを確認
            regular_tab = page.locator(SEAT_SELECTION["regular_tab"])
            if await regular_tab.count() > 0:
                print("📌 普通車タブをクリック")
                await regular_tab.click()
                await page.wait_for_timeout(1000)

            # 価格ラベル（普通車○ など）を取得
            price_labels = await page.locator(SEAT_SELECTION["price_label"]).all()
            print(f"   見つかった商品数: {len(price_labels)}")

            if len(price_labels) > 0:
                print("🎯 最初の商品を選択...")
                await price_labels[0].click()
                await page.wait_for_timeout(2000)
                print("✓ 商品選択完了\n")

                # 商品選択後の状態を保存
                print("📋 ステップ2: 商品選択後の状態")
                await save_page_state(page, "seat_02_after_product_selection")
                print()

                # 座席指定コントロールを探す
                print("🔍 座席指定コントロールを探索中...")

                # パターン1: 「座席指定」を含むボタン
                seat_specify_buttons = await page.locator('button, a, input').filter(has_text="座席指定").all()
                print(f"   「座席指定」を含む要素: {len(seat_specify_buttons)}個")

                # パターン2: 「座席表から指定」を含むボタン
                seat_map_buttons = await page.locator('button, a, input').filter(has_text="座席表から指定").all()
                print(f"   「座席表から指定」を含む要素: {len(seat_map_buttons)}個")

                # パターン3: 「指定なし」を含むボタン
                no_specify_buttons = await page.locator('button, a, input').filter(has_text="指定なし").all()
                print(f"   「指定なし」を含む要素: {len(no_specify_buttons)}個")
                print()

                input("Enterキーを押すと「座席指定：指定なし」ボタンを探してクリックします...")

                # 座席指定：指定なし ボタンを探してクリック
                seat_specify_btn = page.locator('button:has-text("座席指定"), a:has-text("座席指定")').first
                if await seat_specify_btn.count() > 0:
                    print("🎯 「座席指定」ボタンをクリック...")
                    await seat_specify_btn.click()
                    await page.wait_for_timeout(2000)

                    # A/B/C/D/E セレクタが表示された状態を保存
                    print("📋 ステップ3: 座席位置セレクタ表示後")
                    await save_page_state(page, "seat_03_position_selector")
                    print()

                    # A/B/C/D/E ボタンを探す
                    print("🔍 A/B/C/D/E 座席位置ボタンを探索中...")
                    for letter in ['A', 'B', 'C', 'D', 'E']:
                        buttons = await page.locator(f'button:has-text("{letter}"), input[value="{letter}"], label:has-text("{letter}")').all()
                        print(f"   {letter}: {len(buttons)}個")
                    print()
                else:
                    print("⚠️  「座席指定」ボタンが見つかりませんでした")
                    print()

                input("Enterキーを押すと「座席表から指定する」ボタンを探します...")

                # 座席表から指定する ボタンを探す
                seat_map_btn = page.locator('button:has-text("座席表から指定"), a:has-text("座席表から指定")').first
                if await seat_map_btn.count() > 0:
                    print("✓ 「座席表から指定する」ボタンが見つかりました")

                    # ボタンが有効かチェック
                    is_disabled = await seat_map_btn.is_disabled()
                    print(f"   ボタンの状態: {'無効' if is_disabled else '有効'}")

                    if not is_disabled:
                        print("🎯 「座席表から指定する」ボタンをクリック...")
                        await seat_map_btn.click()
                        await page.wait_for_timeout(3000)

                        # 座席表が表示された状態を保存
                        print("📋 ステップ4: 座席表表示後")
                        await save_page_state(page, "seat_04_seat_map")
                        print()
                else:
                    print("⚠️  「座席表から指定する」ボタンが見つかりませんでした")
                    print()

            print("=" * 70)
            print("調査完了")
            print("=" * 70)
            print()
            print("保存されたファイル:")
            print("  - seat_01_initial_*.png/html       : 商品選択前")
            print("  - seat_02_after_product_*.png/html : 商品選択後")
            print("  - seat_03_position_*.png/html      : 座席位置セレクタ表示")
            print("  - seat_04_seat_map_*.png/html      : 座席表表示")
            print()

            input("\nEnterキーを押すとブラウザを閉じます...")

        except Exception as e:
            print(f"\n❌ エラー: {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="investigate_seat_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
