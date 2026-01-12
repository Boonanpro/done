"""
実際の予約購入: 1月30日 東京→新大阪 12時前着

「1月30日東京から新大阪に昼12時前に到着する新幹線買って」
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
from app.executors.ex_reservation.seat import complete_seat_selection
from app.executors.ex_reservation.purchase import execute_purchase
from app.utils.session_manager import SessionManager
from app.utils.gmail_otp_helper import get_sms_otp_from_gmail_async

load_dotenv()

MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")


async def get_otp_from_gmail() -> str:
    """
    Gmail経由でSMS OTPを自動取得

    SMS Forwarder → Gmail → OTP抽出
    EXログインと3DS認証の両方で使用
    """
    print()
    print("=" * 70)
    print("Gmail経由でOTP自動取得中...")
    print("=" * 70)
    print()
    print("SMS Forwarder → Gmail → OTP抽出")
    print("最大2分間待機します...")
    print()

    # SMS転送の遅延を考慮して初回は10秒待機
    print("SMS転送を待機中...")
    await asyncio.sleep(10)
    print()

    # 最大3分間待機してOTPを取得（36回 × 5秒）
    max_attempts = 36

    for attempt in range(1, max_attempts + 1):
        print(f"[{attempt}/{max_attempts}] Gmailをチェック中...")

        otp_code = await get_sms_otp_from_gmail_async(minutes=15)

        if otp_code:
            print()
            print("=" * 70)
            print(f"[SUCCESS] OTP取得: {otp_code}")
            print("=" * 70)
            print()
            return otp_code

        # 5秒待機して再試行
        if attempt < max_attempts:
            await asyncio.sleep(5)

    print()
    print("[TIMEOUT] OTPが見つかりませんでした")
    print()
    print("フォールバック: 手動入力")
    loop = asyncio.get_event_loop()
    otp_code = await loop.run_in_executor(
        None,
        lambda: input("OTP (6桁): ").strip()
    )
    return otp_code


async def main():
    print("=" * 70)
    print("Purchase: Tokyo -> Shin-Osaka, Jan 30, Arrive before 12:00")
    print("=" * 70)
    print()
    print("[REQUEST] 1月30日東京から新大阪に昼12時前に到着する新幹線買って")
    print()
    print("[PARAMETERS]")
    print("  Date: 2026/01/30 (Thu)")
    print("  Route: Tokyo -> Shin-Osaka")
    print("  Arrive: Before 12:00")
    print("  Passengers: 1 adult")
    print()
    print("[WARNING] This will perform ACTUAL purchase!")
    print()

    session_mgr = SessionManager("smartex_multi_test")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # Login
            print("\n[1/6] Login...")
            result = await login(page, MEMBER_ID, PASSWORD)

            if result.requires_otp:
                print("\nOTP authentication required")
                print("Using Gmail OTP auto-retrieval...")
                result = await complete_otp_authentication(page, get_otp_from_gmail)

            if not result.success:
                print(f"Login failed: {result.message}")
                return

            print("[OK] Login successful\n")
            await session_mgr.save_session(context)

            # Search
            print("[2/6] Search train...")
            await open_search_form(page)

            # 12時前着なので、到着時刻で検索
            # 東京-新大阪は約2.5時間なので、9時台出発で12時前着
            print("  Route: Tokyo -> Shin-Osaka")
            print("  Date: 2026/01/30 (Thu)")
            print("  Time: 11:00 arrival (searching for trains arriving before 12:00)")
            print("  Passengers: 1 adult")

            # 到着時刻で検索（11時着で検索すれば12時前着の列車が出る）
            await fill_search_form(
                page,
                departure_station="東京",
                arrival_station="新大阪",
                hour="11時",
                departure_arrival="2",  # 到着時刻（value="2"）
                adult_count=1,
                date="20260130",  # 2026年1月30日
            )
            print("[OK] Search form filled\n")

            search_result = await execute_search(page)
            if not search_result.success:
                print(f"Search failed: {search_result.message}")
                return
            print(f"[OK] {search_result.message}")

            # 候補を表示
            if search_result.options:
                print("\nAvailable trains (arriving before 12:00):")
                for i, option in enumerate(search_result.options[:5]):
                    status = "[O]" if option.available else "[X]"
                    print(f"  [{i}] {option.train_name}")
                    print(f"      {option.departure_time} -> {option.arrival_time} {status}")
                print()

            # Select train (first available)
            print("[3/6] Select first available train...")
            selected_index = 0
            if search_result.options:
                # 最初の空席ありの列車を選択
                for i, option in enumerate(search_result.options):
                    if option.available:
                        selected_index = i
                        print(f"  Selected: {option.train_name} ({option.departure_time} -> {option.arrival_time})")
                        break

            await select_train(page, selected_index)
            print("[OK] Train selected\n")

            # Seat selection
            print("[4/6] Seat selection...")
            print("  Product: First product (SmartEX)")
            print("  Seat position: No preference (to increase availability)")

            seat_result = await complete_seat_selection(
                page,
                product_index=0,
                seat_position="指定なし",
                allow_separate_seats=False,
            )

            if not seat_result.success:
                print(f"Seat selection failed: {seat_result.message}")
                if seat_result.screenshot_path:
                    print(f"Screenshot: {seat_result.screenshot_path}")
                return

            print(f"[OK] {seat_result.message}")
            if seat_result.screenshot_path:
                print(f"Screenshot: {seat_result.screenshot_path}")
            print()

            # Wait a bit to see confirmation screen
            print("[5/6] Review confirmation screen...")
            await page.wait_for_timeout(3000)

            # Purchase
            print("\n[6/6] Execute purchase...")
            print()
            print("=" * 70)
            print("PURCHASING NOW")
            print("=" * 70)
            print()

            # 3DS認証（Gmail OTP自動取得）
            print()
            print("=" * 70)
            print("3D SECURE AUTHENTICATION")
            print("=" * 70)
            print("OTP will be automatically retrieved from Gmail (SMS Forwarder)")
            print()

            purchase_result = await execute_purchase(
                page,
                confirm=True,
                handle_3ds=True,
                otp_callback=get_otp_from_gmail  # Gmail OTP自動取得
            )

            if not purchase_result.success:
                print(f"\n[ERROR] Purchase failed: {purchase_result.message}")
                if purchase_result.screenshot_path:
                    print(f"Screenshot: {purchase_result.screenshot_path}")
                return

            print(f"\n[OK] {purchase_result.message}")
            if purchase_result.reservation_number:
                print(f"  Reservation number: {purchase_result.reservation_number}")
            if purchase_result.screenshot_path:
                print(f"  Screenshot: {purchase_result.screenshot_path}")
            print()

            print("=" * 70)
            print("PURCHASE COMPLETED SUCCESSFULLY")
            print("=" * 70)
            if purchase_result.reservation_number:
                print(f"\nReservation number: {purchase_result.reservation_number}")
            print("\nRoute: Tokyo -> Shin-Osaka")
            print("Date: 2026/01/30 (Thu)")
            print("Arriving before 12:00")
            print()
            print("Next steps:")
            print("  1. Test cancellation executor")
            print("  2. Cancel this reservation")
            print()

            # Wait to see the result
            await page.wait_for_timeout(5000)

        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="buy_tokyo_osaka_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
