"""
同意事項ダイアログ修正テスト

2人分予約で同意事項ダイアログが正しく処理されるかテスト
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
        lambda: input("\nOTP code (6-digit): ").strip()
    )
    return otp_code


async def main():
    print("=" * 70)
    print("Agreement Dialog Fix Test (2 people)")
    print("=" * 70)
    print()

    session_mgr = SessionManager("smartex_multi_test")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # Login
            print("Login...")
            result = await login(page, MEMBER_ID, PASSWORD)

            if result.requires_otp:
                print("\nOTP authentication required")
                result = await complete_otp_authentication(page, get_otp_from_user)

            if not result.success:
                print(f"Login failed: {result.message}")
                return

            print("Login successful\n")
            await session_mgr.save_session(context)

            # Search (2 people)
            await open_search_form(page)
            print("Search: Shin-Osaka -> Hakata 19:00 [2 people]")
            await fill_search_form(page, "新大阪", "博多", "19時", adult_count=2)
            print("Search form filled (2 adults)\n")

            search_result = await execute_search(page)
            if not search_result.success:
                print(f"Search failed: {search_result.message}")
                return
            print(f"Search result: {search_result.message}\n")

            # Select first train
            await select_train(page, 0)
            print("Train selected\n")

            # Seat selection
            print("Seat selection (2 people, adjacent seats)...")
            print("  Product: First product")
            print("  Seat position: Aisle C")
            print("  Allow separate seats: False")

            seat_result = await complete_seat_selection(
                page,
                product_index=0,
                seat_position="通路側C",
                allow_separate_seats=False,
            )

            if not seat_result.success:
                print(f"Seat selection failed: {seat_result.message}")
                if seat_result.screenshot_path:
                    print(f"Screenshot: {seat_result.screenshot_path}")
                return

            print(f"Success: {seat_result.message}")
            if seat_result.screenshot_path:
                print(f"Screenshot: {seat_result.screenshot_path}")
            print()

            print("=" * 70)
            print("Agreement Dialog Fix Test - COMPLETED")
            print("=" * 70)
            print()
            print("Check the confirmation screen:")
            print("  - 2 adults reservation")
            print("  - Adjacent seats allocated")
            print("  - Price for 2 people")
            print()

            input("\nPress Enter to close browser...")

        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="test_agreement_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
