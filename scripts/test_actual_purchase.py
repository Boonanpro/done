"""
実際の予約購入テスト

キャンセル可能な列車を予約購入する
※注意: 実際に決済が行われます。後でキャンセルしてください。
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
from app.executors.ex_reservation.purchase import execute_purchase
from app.utils.session_manager import SessionManager

load_dotenv()

MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")


async def get_otp_from_user() -> str:
    """OTP取得（使用しない - セッション使用のため）"""
    raise RuntimeError("OTP should not be required with saved session")


async def main():
    print("=" * 70)
    print("Actual Purchase Test - CANCELABLE TRAIN")
    print("=" * 70)
    print()
    print("[WARNING] This will perform actual purchase!")
    print("  - Real payment will be charged")
    print("  - Cancel fee will apply if you cancel")
    print("  - Make sure to cancel after testing")
    print()
    print("[AUTO] Proceeding with purchase test...")
    print()

    session_mgr = SessionManager("smartex_multi_test")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # Login
            print("\n[1/5] Login...")
            result = await login(page, MEMBER_ID, PASSWORD)

            if result.requires_otp:
                print("\nOTP authentication required")
                result = await complete_otp_authentication(page, get_otp_from_user)

            if not result.success:
                print(f"Login failed: {result.message}")
                return

            print("[OK] Login successful\n")
            await session_mgr.save_session(context)

            # Search (1 person, near future date)
            print("[2/5] Search train...")
            await open_search_form(page)
            print("  Route: Shin-Osaka -> Kyoto")
            print("  Time: 19:00")
            print("  Passengers: 1 adult")

            await fill_search_form(page, "新大阪", "京都", "19時", adult_count=1)
            print("[OK] Search form filled\n")

            search_result = await execute_search(page)
            if not search_result.success:
                print(f"Search failed: {search_result.message}")
                return
            print(f"[OK] {search_result.message}\n")

            # Select train
            print("[3/5] Select train...")
            await select_train(page, 0)
            print("[OK] Train selected\n")

            # Seat selection
            print("[4/5] Seat selection...")
            print("  Product: First product (SmartEX)")
            print("  Seat position: No preference")

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

            # Purchase
            print("[5/5] Purchase...")
            print()
            print("=" * 70)
            print("EXECUTING PURCHASE")
            print("=" * 70)
            print()

            # Wait a bit to see the confirmation screen
            await page.wait_for_timeout(2000)

            purchase_result = await execute_purchase(page, confirm=True)

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
            print("PURCHASE COMPLETED")
            print("=" * 70)
            if purchase_result.reservation_number:
                print(f"Reservation number: {purchase_result.reservation_number}")
            print()
            print("Next steps:")
            print("  1. Test cancellation executor")
            print("  2. Cancel this reservation to avoid charges")
            print()

            # Wait to see the result
            await page.wait_for_timeout(5000)

        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="test_purchase_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
