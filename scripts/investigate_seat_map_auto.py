"""
座席表選択画面調査スクリプト（OTP自動取得版）

OTPサービスを使用してOTP認証を自動突破
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
from app.executors.ex_reservation.login import login, request_otp, close_otp_dialog, enter_otp
from app.executors.ex_reservation.search import (
    open_search_form,
    fill_search_form,
    execute_search,
    select_train,
)
from app.executors.ex_reservation.seat import select_product
from app.executors.ex_reservation.models import SearchParams
from app.utils.session_manager import SessionManager
from app.services.otp_service import get_otp_service

load_dotenv()

MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")
USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"  # SupabaseユーザーID


async def save_page_info(page, name: str):
    """ページ情報を保存"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

    # スクリーンショット
    screenshot_path = f"seatmap_{name}_{timestamp}.png"
    await page.screenshot(path=screenshot_path, full_page=True)
    print(f"  [IMG] {screenshot_path}")

    # HTML保存
    html = await page.content()
    html_path = f"seatmap_{name}_{timestamp}.html"
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  [HTML] {html_path}")

    return screenshot_path, html_path


async def handle_otp_auto(page) -> bool:
    """OTP認証を自動処理"""
    print("[OTP] OTP認証を自動処理中...")

    # SMS送信リクエスト
    print("[OTP] SMS送信をリクエスト...")
    otp_request_result = await request_otp(page)
    if not otp_request_result.success:
        print(f"[ERROR] OTP送信失敗: {otp_request_result.message}")
        return False

    # ダイアログを閉じる
    print("[OTP] ダイアログを閉じています...")
    await close_otp_dialog(page)

    # OTPサービスでOTPを待機・取得
    print("[OTP] OTPの到着を待機中（最大120秒）...")
    otp_service = get_otp_service()
    otp_code = await otp_service.wait_for_otp(
        user_id=USER_ID,
        service="ex_reservation",
        source="email",  # SMS Forwarder -> Gmail経由
        timeout_seconds=120,
        poll_interval=5,
    )

    if not otp_code:
        print("[ERROR] OTPタイムアウト")
        return False

    print(f"[OTP] OTP取得成功: {otp_code[:2]}****")

    # OTP入力
    print("[OTP] OTPを入力中...")
    otp_result = await enter_otp(page, otp_code)

    if not otp_result.success:
        print(f"[ERROR] OTP認証失敗: {otp_result.message}")
        return False

    print("[OK] OTP認証成功")
    return True


async def main():
    print("=" * 70)
    print("座席表選択画面調査（OTP自動取得版）")
    print("=" * 70)
    print()

    session_mgr = SessionManager("smartex_seatmap_auto")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # ログイン
            print("[LOGIN] ログイン中...")
            result = await login(page, MEMBER_ID, PASSWORD)

            if result.requires_otp:
                print("[OTP] OTP認証が必要です")
                if not await handle_otp_auto(page):
                    print("[ERROR] OTP認証に失敗しました")
                    return

            if not result.success and not result.requires_otp:
                print(f"[ERROR] ログイン失敗: {result.message}")
                return

            print("[OK] ログイン成功")
            await session_mgr.save_session(context)

            # 検索（1人分）
            await open_search_form(page)

            # 明日の日付を計算
            from datetime import timedelta
            tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

            print(f"[SEARCH] 検索条件入力: 新大阪 -> 博多 {tomorrow} 19時")
            search_params = SearchParams(
                departure="新大阪",
                arrival="博多",
                date=tomorrow,
                time="19:00",
                adult_count=1,
            )
            await fill_search_form(page, search_params)

            search_result = await execute_search(page)
            if not search_result.success:
                print(f"[ERROR] 検索失敗: {search_result.message}")
                return

            # 列車選択
            print("[TRAIN] 列車を選択中...")
            await select_train(page, 0)

            # 商品選択
            print("[SEAT] 商品を選択中...")
            await select_product(page, 0)
            await page.wait_for_timeout(2000)
            print("[OK] 商品選択完了")

            # === 座席選択画面を保存 ===
            print()
            print("=" * 70)
            print("座席選択画面の調査")
            print("=" * 70)
            print()

            print("[SAVE] 座席選択画面（商品選択後）")
            await save_page_info(page, "01_seat_selection")
            print()

            # === 座席表から指定するボタンを探す ===
            print("[INSPECT] 座席表ボタンを探索中...")

            # 複数のセレクタパターンを試す
            seat_map_selectors = [
                'button.seat_map_button',
                'button:has-text("座席表から指定")',
                'a:has-text("座席表から指定")',
                'input[value*="座席表"]',
                '.seat_map_button',
                '#seat_map_btn',
            ]

            seat_map_btn = None
            for selector in seat_map_selectors:
                btn = page.locator(selector).first
                count = await btn.count()
                print(f"   {selector}: {count}個")
                if count > 0 and seat_map_btn is None:
                    seat_map_btn = btn

            print()

            if seat_map_btn and await seat_map_btn.count() > 0:
                print("[MAP] 座席表ボタンをクリック...")
                await seat_map_btn.click()
                await page.wait_for_timeout(3000)
                print("[OK] クリック完了")
                print()

                # 座席表画面を保存
                print("[SAVE] 座席表画面")
                await save_page_info(page, "02_seat_map")
                print()

                # 座席表の構造を調査
                print("[INSPECT] 座席表の構造を調査...")
                print()

                # セレクトボックス
                selects = await page.locator('select').all()
                print(f"   セレクトボックス数: {len(selects)}")
                for i, sel in enumerate(selects):
                    sel_id = await sel.get_attribute('id') or ''
                    sel_name = await sel.get_attribute('name') or ''
                    sel_class = await sel.get_attribute('class') or ''
                    print(f"     [{i}] id={sel_id}, name={sel_name}, class={sel_class}")
                print()

                # 座席関連要素
                seat_patterns = [
                    'button[class*="seat"]',
                    'td[class*="seat"]',
                    '.seat',
                    '[class*="zaseki"]',
                    'input[type="radio"]',
                    'label[class*="seat"]',
                ]
                for pattern in seat_patterns:
                    elements = await page.locator(pattern).all()
                    print(f"   {pattern}: {len(elements)}個")
                print()

                # テーブル構造
                tables = await page.locator('table').all()
                print(f"   テーブル数: {len(tables)}")
                for i, tbl in enumerate(tables):
                    tbl_class = await tbl.get_attribute('class') or ''
                    tbl_id = await tbl.get_attribute('id') or ''
                    rows = await tbl.locator('tr').count()
                    print(f"     [{i}] id={tbl_id}, class={tbl_class}, rows={rows}")
                print()

                # ボタン
                buttons = await page.locator('button, input[type="button"], input[type="submit"]').all()
                print(f"   ボタン数: {len(buttons)}")
                for i, btn in enumerate(buttons[:10]):  # 最初の10個
                    btn_text = await btn.text_content() or ''
                    btn_value = await btn.get_attribute('value') or ''
                    btn_class = await btn.get_attribute('class') or ''
                    print(f"     [{i}] text={btn_text[:20]}, value={btn_value[:20]}, class={btn_class[:30]}")
                print()

            else:
                print("[WARN] 座席表ボタンが見つかりません")
                print()

                # 現在のページ構造を詳細調査
                print("[INSPECT] 現在のページ構造を詳細調査...")

                # 全てのボタンを列挙
                all_buttons = await page.locator('button, input[type="button"], input[type="submit"], a.button').all()
                print(f"   全ボタン数: {len(all_buttons)}")
                for i, btn in enumerate(all_buttons):
                    btn_text = (await btn.text_content() or '').strip()[:30]
                    btn_value = (await btn.get_attribute('value') or '')[:30]
                    btn_class = (await btn.get_attribute('class') or '')[:40]
                    print(f"     [{i}] text=\"{btn_text}\" value=\"{btn_value}\" class=\"{btn_class}\"")
                print()

            print("=" * 70)
            print("調査完了")
            print("=" * 70)
            print()
            print("保存されたファイル:")
            print("  - seatmap_01_seat_selection_*.png/html : 座席選択画面")
            print("  - seatmap_02_seat_map_*.png/html : 座席表画面（あれば）")
            print()

        except Exception as e:
            print(f"[ERROR] エラー: {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="investigate_seatmap_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
