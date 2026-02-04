"""
座席表機能テストスクリプト

セレクタが正しく動作するか確認
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from dotenv import load_dotenv
import os

from app.executors.ex_reservation.login import login, request_otp, close_otp_dialog, enter_otp
from app.executors.ex_reservation.search import (
    open_search_form,
    fill_search_form,
    execute_search,
    select_train,
)
from app.executors.ex_reservation.seat import select_product
from app.executors.ex_reservation.seat_map import (
    open_seat_map,
    get_seat_map_info,
    select_seat_from_map,
    find_seats_with_adjacent_empty,
)
from app.executors.ex_reservation.models import SearchParams
from app.utils.session_manager import SessionManager
from app.services.otp_service import get_otp_service

load_dotenv()

MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")
USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"


async def handle_otp_auto(page) -> bool:
    """OTP認証を自動処理"""
    print("[OTP] OTP認証を自動処理中...")

    otp_request_result = await request_otp(page)
    if not otp_request_result.success:
        print(f"[ERROR] OTP送信失敗: {otp_request_result.message}")
        return False

    await close_otp_dialog(page)

    print("[OTP] OTPの到着を待機中...")
    otp_service = get_otp_service()
    otp_code = await otp_service.wait_for_otp(
        user_id=USER_ID,
        service="ex_reservation",
        source="email",
        timeout_seconds=120,
        poll_interval=5,
    )

    if not otp_code:
        print("[ERROR] OTPタイムアウト")
        return False

    print(f"[OTP] OTP取得成功: {otp_code[:2]}****")

    otp_result = await enter_otp(page, otp_code)
    if not otp_result.success:
        print(f"[ERROR] OTP認証失敗: {otp_result.message}")
        return False

    print("[OK] OTP認証成功")
    return True


async def main():
    print("=" * 70)
    print("座席表機能テスト")
    print("=" * 70)
    print()

    session_mgr = SessionManager("smartex_seat_test")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # ログイン
            print("[LOGIN] ログイン中...")
            result = await login(page, MEMBER_ID, PASSWORD)

            if result.requires_otp:
                if not await handle_otp_auto(page):
                    return

            print("[OK] ログイン成功")
            await session_mgr.save_session(context)

            # 検索
            await open_search_form(page)
            tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            print(f"[SEARCH] 検索: 新大阪 -> 博多 {tomorrow} 19:00")

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

            # 列車・商品選択
            await select_train(page, 0)
            await select_product(page, 0)
            await page.wait_for_timeout(2000)

            # === 座席表テスト ===
            print()
            print("=" * 70)
            print("座席表機能テスト")
            print("=" * 70)
            print()

            # 1. 座席表を開く
            print("[TEST 1] 座席表を開く...")
            if not await open_seat_map(page):
                print("[FAIL] 座席表を開けませんでした")
                return
            print("[PASS] 座席表を開きました")
            print()

            # 2. 座席情報を取得
            print("[TEST 2] 座席情報を取得...")
            seat_info = await get_seat_map_info(page)
            if not seat_info:
                print("[FAIL] 座席情報を取得できませんでした")
                return

            print(f"[PASS] 座席情報取得成功")
            print(f"       号車: {seat_info.car_number}号車")
            print(f"       空席数: {len(seat_info.available_seats)}")
            print(f"       空席例: {seat_info.available_seats[:10]}")
            print()

            # 3. 隣が空いている席を検索
            print("[TEST 3] 隣が空いている席を検索...")
            adjacent_seats = find_seats_with_adjacent_empty(seat_info.seat_layout)
            print(f"[PASS] 隣が空いている席: {len(adjacent_seats)}席")
            if adjacent_seats:
                print(f"       例: {adjacent_seats[:5]}")
            print()

            # 4. 座席を選択（最初の空席）
            if seat_info.available_seats:
                first_seat = seat_info.available_seats[0]
                # "19A" -> row=19, letter="A"
                import re
                match = re.match(r'(\d+)([A-E])', first_seat)
                if match:
                    row = int(match.group(1))
                    letter = match.group(2)

                    print(f"[TEST 4] 座席を選択: {row}番{letter}席...")
                    if await select_seat_from_map(page, seat_info.car_number, row, letter):
                        print(f"[PASS] 座席 {row}番{letter}席 を選択しました")
                    else:
                        print(f"[FAIL] 座席選択に失敗")
            print()

            # スクリーンショット
            screenshot_path = f"test_seat_map_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            await page.screenshot(path=screenshot_path)
            print(f"[SAVE] {screenshot_path}")

            print()
            print("=" * 70)
            print("テスト完了")
            print("=" * 70)

        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="test_seat_map_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
