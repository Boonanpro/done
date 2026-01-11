"""
複数人予約時の座席選択画面調査スクリプト

2人分で予約した場合の座席選択画面の構造を確認
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
    screenshot_path = f"multi_{name}_{timestamp}.png"
    await page.screenshot(path=screenshot_path, full_page=True)
    print(f"  📸 {screenshot_path}")

    # HTML保存
    html = await page.content()
    html_path = f"multi_{name}_{timestamp}.html"
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  📄 {html_path}")


async def main():
    print("=" * 70)
    print("複数人予約 座席選択画面調査")
    print("=" * 70)
    print()

    session_mgr = SessionManager("smartex_multi_investigation")

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

            # ★★★ 重要: 2人分で検索 ★★★
            print("📝 検索条件入力: 新大阪 → 博多 19時 【2人】")
            if not await fill_search_form(
                page,
                departure_station="新大阪",
                arrival_station="博多",
                hour="19時",
                adult_count=2,  # ★ 2人分
            ):
                print("❌ 検索条件の入力に失敗しました")
                return
            print("✓ 検索条件入力完了（大人2名）\n")

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

            # === 座席選択画面の調査 ===
            print("=" * 70)
            print("座席選択画面（2人分）の調査")
            print("=" * 70)
            print()

            # 初期状態を保存
            print("📋 ステップ1: 座席選択画面の初期状態（2人分）")
            await save_page_info(page, "01_seat_selection_initial")
            print()

            input("Enterキーを押すと商品（普通車）を選択します...")

            # 商品選択（1人目と2人目で別々か、まとめてか確認）
            price_labels = await page.locator('label.ticket_btn').all()
            print(f"📊 商品ラベル数: {len(price_labels)}")

            if len(price_labels) > 0:
                print("🎯 最初の商品を選択...")
                await price_labels[0].click()
                await page.wait_for_timeout(2000)

                print("\n📋 ステップ2: 商品選択後の状態")
                await save_page_info(page, "02_after_product_selection")
                print()

                # 座席位置セレクタを調査
                print("🔍 座席位置セレクタの調査...")
                seat_selects = await page.locator('select[name^="hd"]').all()
                print(f"   座席位置セレクトボックス数: {len(seat_selects)}")

                for i, select in enumerate(seat_selects):
                    name = await select.get_attribute('name')
                    id_attr = await select.get_attribute('id')
                    print(f"   [{i}] name={name}, id={id_attr}")
                print()

                # 座席表から指定するボタンの状態
                seat_map_buttons = await page.locator('button.seat_map_button').all()
                print(f"🗺️  座席表から指定するボタン数: {len(seat_map_buttons)}")
                if len(seat_map_buttons) > 0:
                    is_disabled = await seat_map_buttons[0].is_disabled()
                    print(f"   ボタンの状態: {'無効' if is_disabled else '有効'}")
                print()

            print("=" * 70)
            print("調査完了")
            print("=" * 70)
            print()
            print("保存されたファイル:")
            print("  - multi_01_seat_selection_initial_*.png/html  : 座席選択画面初期状態（2人分）")
            print("  - multi_02_after_product_selection_*.png/html : 商品選択後の状態")
            print()
            print("次の確認事項:")
            print("  1. 座席位置セレクトボックスが2つあるか（1人につき1つ）")
            print("  2. それとも1つのセレクタで2人分まとめて選択するのか")
            print("  3. 座席表から指定する機能で隣り合う席を選べるか")
            print()

            input("\nEnterキーを押すとブラウザを閉じます...")

        except Exception as e:
            print(f"\n❌ エラー: {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="investigate_multi_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
