"""
EX Cancellation Flow Investigation - Real Implementation

Properly logs in with OTP and investigates actual selectors
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
from app.utils.session_manager import SessionManager
from app.utils.gmail_otp_helper import get_sms_otp_from_gmail_async

load_dotenv()

MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")


async def get_otp_from_gmail() -> str:
    """Gmail経由でOTPを取得"""
    print()
    print("=" * 70)
    print("Gmail経由でOTP自動取得中...")
    print("=" * 70)
    print()

    # SMS転送の遅延を考慮
    print("SMS転送を待機中...")
    await asyncio.sleep(10)
    print()

    # 最大3分間待機
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

        if attempt < max_attempts:
            await asyncio.sleep(5)

    print()
    print("[TIMEOUT] OTPが見つかりませんでした")
    return ""


async def save_page_state(page, step_name):
    """Save page state"""
    screenshot_path = f"ex_cancel_real_{step_name}.png"
    html_path = f"ex_cancel_real_{step_name}.html"

    await page.screenshot(path=screenshot_path, full_page=True)
    html = await page.content()
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  [Screenshot] {screenshot_path}")
    print(f"  [HTML] {html_path}")

    return screenshot_path, html_path


async def main():
    print("=" * 70)
    print("EX Cancellation Flow - Real Investigation")
    print("=" * 70)
    print()
    print("Target: Reservation 2073")
    print()

    session_mgr = SessionManager("smartex_cancel_real")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # Login
            print("[1/6] Login...")
            result = await login(page, MEMBER_ID, PASSWORD)

            if not result.success:
                print(f"  [ERROR] Login failed: {result.message}")
                return

            print("[OK] Login successful\n")
            await session_mgr.save_session(context)

            # OTP画面が表示されているか確認
            print("[1b/6] Checking for OTP screen...")
            sms_button = page.locator('text="SMS送信"').first

            if await sms_button.count() > 0:
                print("  [INFO] OTP screen detected")

                # SMS送信ボタンをクリック
                print("  [INFO] Clicking SMS send button...")
                await sms_button.click()
                await page.wait_for_timeout(2000)

                # GmailからOTPを取得
                otp_code = await get_otp_from_gmail()

                if not otp_code:
                    print("  [ERROR] Failed to get OTP")
                    return

                # OTPを入力
                print(f"  [INFO] Entering OTP: {otp_code[:3]}***")

                # OTP入力フィールドを探す（type="tel"）
                await page.wait_for_timeout(2000)  # フィールドが表示されるまで待機
                otp_input = page.locator('input[type="tel"], input[name="tx01"]').first

                if await otp_input.count() == 0:
                    print("  [ERROR] OTP input field not found")
                    await page.screenshot(path="ex_cancel_otp_input_error.png")
                    html = await page.content()
                    with open("ex_cancel_otp_input_error.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    print("  [INFO] HTML saved")

                    # 全てのinput要素を表示
                    all_inputs = await page.locator('input').all()
                    print(f"  [DEBUG] Found {len(all_inputs)} input elements:")
                    for i, inp in enumerate(all_inputs):
                        try:
                            inp_type = await inp.get_attribute('type')
                            inp_name = await inp.get_attribute('name')
                            inp_id = await inp.get_attribute('id')
                            print(f"    [{i}] type='{inp_type}' name='{inp_name}' id='{inp_id}'")
                        except:
                            pass
                    return

                await otp_input.fill(otp_code)
                await page.wait_for_timeout(1000)
                print("  [OK] OTP entered")

                # SMSダイアログを閉じる
                close_dialog = page.locator('text="閉じる"').first
                if await close_dialog.count() > 0:
                    print("  [INFO] Closing SMS dialog...")
                    await close_dialog.click()
                    await page.wait_for_timeout(1000)

                # OK次へボタンをクリック
                print("  [INFO] Clicking OK button...")

                # 画面をスクロールダウン
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1000)

                # OK次へボタンを探す（name="b2"のsubmitボタン）
                ok_button = page.locator('input[type="submit"][name="b2"]').first

                if await ok_button.count() == 0:
                    # "OK 次へ"テキストで試す
                    ok_button = page.locator('text="OK 次へ"').first

                if await ok_button.count() == 0:
                    # "OK"だけでも試す
                    ok_button = page.locator('button >> text="OK"').first

                if await ok_button.count() == 0:
                    print("  [ERROR] OK button not found")
                    await page.screenshot(path="ex_cancel_ok_button_error.png", full_page=True)

                    # 全てのボタンを表示
                    all_buttons = await page.locator('button, input[type="button"], input[type="submit"]').all()
                    print(f"  [DEBUG] Found {len(all_buttons)} buttons:")
                    for i, btn in enumerate(all_buttons[:10]):
                        try:
                            btn_text = await btn.text_content()
                            btn_value = await btn.get_attribute('value')
                            btn_type = await btn.get_attribute('type')
                            print(f"    [{i}] type='{btn_type}' text='{btn_text}' value='{btn_value}'")
                        except:
                            pass
                    return

                await ok_button.click()
                await page.wait_for_timeout(3000)

                print("  [OK] OTP authentication completed\n")
            else:
                print("  [INFO] No OTP required\n")

            await save_page_state(page, "step1_logged_in")
            print()

            # Navigate to reservation menu
            print("[2/6] Navigate to reservation menu...")

            # メニューボタンを探す
            menu_button = page.locator('button:has-text("メニュー"), a:has-text("メニュー")').first
            if await menu_button.count() > 0:
                print("  [OK] Found menu button")
                await menu_button.click()
                await page.wait_for_timeout(2000)
            else:
                print("  [INFO] Menu button not found, may already be on menu page")

            await save_page_state(page, "step2_after_menu")
            print()

            # 予約確認・変更・払戻を探す
            print("[3/6] Looking for reservation confirmation menu...")

            # より具体的なセレクタで検索
            reservation_menu_selectors = [
                'text="予約確認・変更・払戻"',
                'text="予約確認・変更"',
                'text="予約確認"',
                'a:has-text("確認")',
                'a:has-text("払戻")',
            ]

            reservation_link = None
            for selector in reservation_menu_selectors:
                count = await page.locator(selector).count()
                if count > 0:
                    text_content = await page.locator(selector).first.text_content()
                    print(f"  [FOUND] {selector}: '{text_content.strip()}'")

                    # "予約"だけでなく"確認"や"変更"が含まれているか確認
                    if "確認" in text_content or "変更" in text_content or "払戻" in text_content:
                        print(f"  [OK] Using: {selector}")
                        reservation_link = page.locator(selector).first
                        break

            if reservation_link:
                await reservation_link.click()
                await page.wait_for_timeout(3000)
                print("  [OK] Clicked reservation menu\n")
            else:
                print("  [ERROR] Reservation menu not found\n")
                return

            await save_page_state(page, "step3_reservation_list")
            print()

            # 予約番号2073を探す
            print("[4/6] Looking for reservation 2073...")

            # より広いセレクタで予約を探す
            reservation_2073 = page.locator(':text-matches("2073")').first

            if await reservation_2073.count() == 0:
                # 部分一致で試す
                reservation_2073 = page.get_by_text("2073", exact=False).first

            if await reservation_2073.count() > 0:
                print("  [OK] Found reservation 2073")
                # 予約カード全体のスクリーンショット
                await save_page_state(page, "step4_reservation_card")
            else:
                print("  [ERROR] Reservation 2073 not found")
                # デバッグ: 予約番号を含む要素を探す
                all_text = await page.locator('body').text_content()
                if "2073" in all_text:
                    print("  [DEBUG] '2073' exists in page text but locator failed")
                print("  Trying to proceed anyway...")
                await save_page_state(page, "step4_reservation_card")

            print()

            # 払戻ボタンを探す
            print("[5/6] Looking for refund button...")

            # より広いセレクタで払戻ボタンを探す
            refund_button_selectors = [
                'text="払戻"',
                'button:has-text("払戻")',
                'a:has-text("払戻")',
                'input[type="button"][value*="払戻"]',
            ]

            refund_button = None
            for selector in refund_button_selectors:
                elements = await page.locator(selector).all()
                if elements:
                    print(f"  [FOUND] '{selector}': {len(elements)} elements")
                    for i, elem in enumerate(elements):
                        try:
                            tag = await elem.evaluate("el => el.tagName")
                            elem_text = await elem.text_content() if tag != 'INPUT' else await elem.get_attribute('value')
                            elem_class = await elem.evaluate("el => el.className || ''")
                            print(f"    [{i}] <{tag}> class='{elem_class[:40]}' text='{elem_text}'")
                        except:
                            pass

                    # 最初の要素を使用
                    refund_button = elements[0]
                    break

            if not refund_button:
                print("  [ERROR] Refund button not found")
                return

            print()
            print("  [INFO] Clicking refund button...")

            # input要素（実際のボタン）を直接クリック
            actual_button = page.locator('input[type="submit"][value*="払戻"], input[id="sb-1"]').first
            if await actual_button.count() > 0:
                print("  [INFO] Found actual submit button, clicking it...")
                await actual_button.click(force=True)  # force click to bypass overlay
            else:
                # フォールバック
                await refund_button.click(force=True)

            await page.wait_for_timeout(3000)
            print("  [OK] Clicked refund button\n")

            await save_page_state(page, "step5_refund_confirm")
            print()

            # 確認画面のボタンを分析
            print("[6/6] Analyzing refund confirmation page...")

            # 全てのボタンとリンクを表示
            all_buttons = await page.locator('button, a, input[type="button"], input[type="submit"]').all()
            print(f"  [INFO] Found {len(all_buttons)} buttons/links on confirmation page:")

            for i, btn in enumerate(all_buttons[:15]):
                try:
                    tag = await btn.evaluate("el => el.tagName")
                    btn_text = await btn.text_content()
                    btn_value = await btn.get_attribute('value')
                    btn_name = await btn.get_attribute('name')
                    btn_id = await btn.get_attribute('id')
                    btn_class = await btn.evaluate("el => el.className || ''")

                    display_text = btn_text.strip() if btn_text and btn_text.strip() else btn_value
                    if display_text:
                        print(f"    [{i}] <{tag}> name='{btn_name}' id='{btn_id}' class='{btn_class[:30]}'")
                        print(f"        text/value='{display_text[:50]}'")
                except:
                    pass

            print()
            print("=" * 70)
            print("[COMPLETE] Investigation finished!")
            print("=" * 70)
            print()
            print("[WARNING] 実際のキャンセルは実行していません")
            print()
            print("Saved files:")
            print("  - ex_cancel_real_step1_logged_in.png/html")
            print("  - ex_cancel_real_step2_after_menu.png/html")
            print("  - ex_cancel_real_step3_reservation_list.png/html")
            print("  - ex_cancel_real_step4_reservation_card.png/html")
            print("  - ex_cancel_real_step5_refund_confirm.png/html")
            print()
            print("Next steps:")
            print("  1. Review confirmation page selectors")
            print("  2. Implement cancel executor")
            print("  3. Test with actual cancellation")
            print()

            # 最後に少し待機
            await page.wait_for_timeout(10000)

        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="ex_cancel_real_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
