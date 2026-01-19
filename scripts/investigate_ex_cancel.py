"""
EXキャンセルフローの調査

予約番号2073のキャンセル手順を確認し、セレクタを記録
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
from app.utils.session_manager import SessionManager

load_dotenv()

MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")


async def main():
    print("=" * 70)
    print("EX Cancellation Flow Investigation")
    print("=" * 70)
    print()
    print("Target: Reservation 2073")
    print()

    session_mgr = SessionManager("smartex_cancel_investigation")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # Login
            print("[1] Login...")
            result = await login(page, MEMBER_ID, PASSWORD)

            if not result.success:
                print(f"Login failed: {result.message}")
                return

            print("[OK] Login successful\n")
            await session_mgr.save_session(context)

            # マイページに移動（ログイン後の画面）
            print("[2] Navigate to My Page...")
            current_url = page.url
            print(f"  Current URL: {current_url}")

            # スクリーンショット
            await page.screenshot(path="ex_cancel_01_after_login.png")
            print("  Screenshot: ex_cancel_01_after_login.png")

            # HTMLを保存
            html = await page.content()
            with open("ex_cancel_01_after_login.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("  HTML saved: ex_cancel_01_after_login.html")
            print()

            # 予約確認ボタンを探す
            print("[3] Looking for reservation confirmation button...")

            # 可能性のあるボタンテキスト
            possible_texts = [
                "予約確認",
                "予約の確認",
                "予約・変更",
                "予約確認・変更・払戻",
                "予約確認・変更",
                "マイページ",
            ]

            for text in possible_texts:
                elements = await page.locator(f'text="{text}"').all()
                if elements:
                    print(f"  Found: '{text}' ({len(elements)} elements)")
                    for i, elem in enumerate(elements):
                        tag = await elem.evaluate("el => el.tagName")
                        print(f"    [{i}] <{tag}>")

            print()
            print("Available buttons/links:")
            links = await page.locator('a, button').all()
            for i, link in enumerate(links[:20]):  # 最初の20個のみ
                try:
                    text = await link.text_content()
                    if text and text.strip():
                        print(f"  [{i}] {text.strip()[:50]}")
                except:
                    pass

            print()
            print("[Manual] Please navigate to the reservation list and press Enter")
            input("Press Enter after you see the reservation list...")

            # 現在の画面を記録
            print()
            print("[4] Recording reservation list page...")
            await page.screenshot(path="ex_cancel_02_reservation_list.png")
            html = await page.content()
            with open("ex_cancel_02_reservation_list.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("  Screenshot: ex_cancel_02_reservation_list.png")
            print("  HTML saved: ex_cancel_02_reservation_list.html")
            print()

            # 予約番号2073を探す
            print("[5] Looking for reservation 2073...")
            reservation_elements = await page.locator('text="2073"').all()
            print(f"  Found {len(reservation_elements)} elements containing '2073'")

            print()
            print("[Manual] Please click on reservation 2073 and press Enter")
            input("Press Enter after reservation detail is shown...")

            # 予約詳細画面を記録
            print()
            print("[6] Recording reservation detail page...")
            await page.screenshot(path="ex_cancel_03_reservation_detail.png")
            html = await page.content()
            with open("ex_cancel_03_reservation_detail.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("  Screenshot: ex_cancel_03_reservation_detail.png")
            print("  HTML saved: ex_cancel_03_reservation_detail.html")
            print()

            # キャンセルボタンを探す
            print("[7] Looking for cancel button...")
            cancel_texts = [
                "キャンセル",
                "払戻",
                "払い戻し",
                "取消",
                "取り消し",
            ]

            for text in cancel_texts:
                elements = await page.locator(f'text="{text}"').all()
                if elements:
                    print(f"  Found: '{text}' ({len(elements)} elements)")
                    for i, elem in enumerate(elements):
                        tag = await elem.evaluate("el => el.tagName")
                        elem_id = await elem.evaluate("el => el.id")
                        elem_class = await elem.evaluate("el => el.className")
                        print(f"    [{i}] <{tag}> id='{elem_id}' class='{elem_class}'")

            print()
            print("[Manual] Please click the cancel button and press Enter")
            input("Press Enter after cancel confirmation page is shown...")

            # キャンセル確認画面を記録
            print()
            print("[8] Recording cancel confirmation page...")
            await page.screenshot(path="ex_cancel_04_confirm.png")
            html = await page.content()
            with open("ex_cancel_04_confirm.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("  Screenshot: ex_cancel_04_confirm.png")
            print("  HTML saved: ex_cancel_04_confirm.html")
            print()

            # 確認ボタンを探す
            print("[9] Looking for confirmation button...")
            confirm_texts = [
                "払戻を実行",
                "キャンセルを実行",
                "実行",
                "確認",
                "はい",
            ]

            for text in confirm_texts:
                elements = await page.locator(f'text="{text}"').all()
                if elements:
                    print(f"  Found: '{text}' ({len(elements)} elements)")

            print()
            print("[WARNING] Do NOT click the final cancel button!")
            print("Investigation complete. Check saved HTML files for selectors.")
            print()

            # 最後に少し待機
            await page.wait_for_timeout(5000)

        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="ex_cancel_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
