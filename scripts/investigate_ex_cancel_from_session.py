"""
EXキャンセルフローの調査（既存セッションを使用）

既にログイン済みのセッションを使用して予約確認画面から調査
"""
import asyncio
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from dotenv import load_dotenv
from app.utils.session_manager import SessionManager

load_dotenv()


async def main():
    print("=" * 70)
    print("EX Cancellation Flow Investigation (From Session)")
    print("=" * 70)
    print()

    # 既存のセッションを使用
    session_mgr = SessionManager("smartex_multi_test")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # EXのトップページに移動
            print("[1] Navigate to EX top page...")
            await page.goto("https://shinkansen2.jr-central.co.jp/RSV_P/ClientService")
            await page.wait_for_timeout(3000)

            await page.screenshot(path="ex_cancel_step1_top.png")
            html = await page.content()
            with open("ex_cancel_step1_top.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("  Screenshot: ex_cancel_step1_top.png")
            print()

            # ページ上のボタン/リンクを全て表示
            print("[2] Available buttons and links:")
            buttons = await page.locator('a, button, input[type="button"], input[type="submit"]').all()
            for i, btn in enumerate(buttons[:30]):
                try:
                    text = await btn.text_content()
                    if text and text.strip():
                        tag = await btn.evaluate("el => el.tagName")
                        btn_id = await btn.evaluate("el => el.id || ''")
                        href = await btn.evaluate("el => el.href || el.onclick || ''")
                        print(f"  [{i:2d}] <{tag:6s}> id='{btn_id:20s}' text='{text.strip()[:30]:30s}' href/onclick='{str(href)[:40]}'")
                except:
                    pass

            print()
            print("[3] Looking for reservation/menu buttons...")

            # メニューボタンを探す
            menu_selectors = [
                'text="メニュー"',
                'button:has-text("メニュー")',
                'a:has-text("メニュー")',
                '#menu',
                '.menu',
            ]

            for selector in menu_selectors:
                count = await page.locator(selector).count()
                if count > 0:
                    print(f"  Found menu: {selector} ({count} elements)")

            # 予約関連のリンクを探す
            reservation_selectors = [
                'text="予約確認"',
                'text="予約"',
                'a:has-text("予約")',
                'button:has-text("予約")',
            ]

            for selector in reservation_selectors:
                count = await page.locator(selector).count()
                if count > 0:
                    print(f"  Found reservation: {selector} ({count} elements)")

            print()
            print("[Manual Step] Please navigate to reservation list manually.")
            print("Look for '予約確認・変更・払戻' or similar menu item.")
            print()
            input("Press Enter when you reach the reservation list...")

            # 予約一覧画面を記録
            print()
            print("[4] Recording reservation list...")
            await page.screenshot(path="ex_cancel_step2_list.png")
            html = await page.content()
            with open("ex_cancel_step2_list.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("  Screenshot: ex_cancel_step2_list.png")
            print("  HTML saved: ex_cancel_step2_list.html")
            print()

            # 予約番号2073を探す
            print("[5] Looking for reservation 2073...")
            reservation_2073 = await page.locator('text="2073"').all()
            print(f"  Found {len(reservation_2073)} elements containing '2073'")

            if reservation_2073:
                print()
                print("[Manual Step] Please click on reservation 2073.")
                input("Press Enter when you see the reservation detail...")

                # 予約詳細画面を記録
                print()
                print("[6] Recording reservation detail...")
                await page.screenshot(path="ex_cancel_step3_detail.png")
                html = await page.content()
                with open("ex_cancel_step3_detail.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("  Screenshot: ex_cancel_step3_detail.png")
                print("  HTML saved: ex_cancel_step3_detail.html")
                print()

                # キャンセル/払戻ボタンを探す
                print("[7] Looking for cancel/refund buttons...")
                cancel_keywords = ["払戻", "払い戻し", "キャンセル", "取消", "取り消し"]

                for keyword in cancel_keywords:
                    elements = await page.locator(f'text="{keyword}"').all()
                    if elements:
                        print(f"  Keyword '{keyword}': {len(elements)} elements")
                        for i, elem in enumerate(elements[:3]):
                            try:
                                tag = await elem.evaluate("el => el.tagName")
                                elem_id = await elem.evaluate("el => el.id || ''")
                                elem_class = await elem.evaluate("el => el.className || ''")
                                elem_text = await elem.text_content()
                                print(f"    [{i}] <{tag}> id='{elem_id}' class='{elem_class[:40]}' text='{elem_text.strip()[:40]}'")
                            except:
                                pass

                # 全てのボタンを表示
                print()
                print("  All buttons on detail page:")
                buttons = await page.locator('button, a.button, input[type="button"], input[type="submit"]').all()
                for i, btn in enumerate(buttons[:20]):
                    try:
                        text = await btn.text_content()
                        if text and text.strip():
                            tag = await btn.evaluate("el => el.tagName")
                            btn_id = await btn.evaluate("el => el.id || ''")
                            btn_class = await btn.evaluate("el => el.className || ''")
                            print(f"    [{i:2d}] <{tag}> id='{btn_id:20s}' class='{btn_class[:30]:30s}' text='{text.strip()[:40]}'")
                    except:
                        pass

            print()
            print("[INFO] Investigation complete!")
            print("[WARNING] Do NOT click the cancel button to preserve the reservation.")
            print()

            # 最後に少し待機
            await page.wait_for_timeout(10000)

        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="ex_cancel_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
