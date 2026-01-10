"""
SmartEX OTP画面のボタンを詳細調査するスクリプト

OTP入力後のOKボタンと閉じるボタンの正確なセレクタを特定
"""
import asyncio
import os
import sys
from pathlib import Path

# プロジェクトルートをPATHに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from dotenv import load_dotenv

# .envファイルを読み込み
load_dotenv()

# 認証情報を環境変数から取得
MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")
LOGIN_URL = "https://shinkansen2.jr-central.co.jp/RSV_P/smart_index.htm"


async def main():
    print("=" * 70)
    print("SmartEX OTP画面ボタン詳細調査")
    print("=" * 70)
    print()

    if not MEMBER_ID or not PASSWORD:
        print("Error: .envファイルにEX_MEMBER_IDとEX_PASSWORDを設定してください")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=1000)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="ja-JP",
        )
        page = await context.new_page()

        try:
            # Step 1: ログイン
            print("Step 1: ログインページにアクセス")
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            print("Step 2: ID/パスワード入力")
            await page.locator('role=textbox[name="会員ID"]').fill(MEMBER_ID)
            await page.wait_for_timeout(500)
            await page.locator('role=textbox[name="パスワード"]').fill(PASSWORD)
            await page.wait_for_timeout(500)

            print("Step 3: ログインボタンクリック")
            await page.locator('role=button[name="ログイン"]').click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(3000)

            print(f"\n現在のURL: {page.url}\n")

            # Step 4: 自動音声案内発信ボタンをクリック
            print("Step 4: 自動音声案内発信ボタンをクリック")
            send_button = page.locator('input[value="自動音声案内発信"]')
            if await send_button.count() > 0:
                print("  ✓ 発信ボタンが見つかりました")
                await send_button.click()
                await page.wait_for_timeout(3000)
                print("  ✓ ボタンをクリックしました")
            else:
                print("  × 発信ボタンが見つかりません")

            # Step 5: 閉じるボタンを調査
            print("\nStep 5: 「閉じる」ボタンを詳細調査")
            close_selectors = [
                'button:has-text("閉じる")',
                'input[value="閉じる"]',
                'input[type="button"][value="閉じる"]',
                'input[type="submit"][value="閉じる"]',
                '[onclick*="close"]',
                'button:has-text("Close")',
            ]

            for selector in close_selectors:
                locator = page.locator(selector)
                count = await locator.count()
                if count > 0:
                    print(f"  ✓ 見つかった: {selector} (数: {count})")
                    try:
                        is_visible = await locator.first.is_visible()
                        is_enabled = await locator.first.is_enabled()
                        print(f"    - 表示: {is_visible}, 有効: {is_enabled}")
                    except Exception as e:
                        print(f"    - エラー: {e}")

            # 全てのボタンを列挙
            print("\n  全ボタン一覧:")
            all_buttons = await page.locator('button, input[type="button"], input[type="submit"]').all()
            for i, btn in enumerate(all_buttons):
                try:
                    is_visible = await btn.is_visible()
                    if is_visible:
                        tag = await btn.evaluate("el => el.tagName")
                        type_attr = await btn.evaluate("el => el.type")
                        value = await btn.evaluate("el => el.value || el.textContent")
                        print(f"    {i+1}. <{tag} type={type_attr}> \"{value}\"")
                except Exception:
                    pass

            print("\n" + "=" * 70)
            print("ダイアログが表示されている場合は手動で閉じてください")
            print("その後、OTP入力画面のボタンを調査します")
            print("=" * 70)
            input("\nEnterキーを押して続行...")

            # Step 6: OTP入力フィールドを調査
            print("\nStep 6: OTP入力フィールドを調査")
            otp_selectors = [
                'input[type="tel"]',
                'input[name*="otp"]',
                'input[name*="password"]',
                'input[maxlength="6"]',
                'input[placeholder*="パスワード"]',
            ]

            for selector in otp_selectors:
                locator = page.locator(selector)
                count = await locator.count()
                if count > 0:
                    print(f"  ✓ 見つかった: {selector} (数: {count})")
                    try:
                        is_visible = await locator.first.is_visible()
                        is_enabled = await locator.first.is_enabled()
                        print(f"    - 表示: {is_visible}, 有効: {is_enabled}")
                    except Exception as e:
                        print(f"    - エラー: {e}")

            # Step 7: OKボタンを詳細調査
            print("\nStep 7: OKボタンを詳細調査")
            ok_selectors = [
                'input[value*="OK"]',
                'input[value="OK"]',
                'button:has-text("OK")',
                'input[type="submit"]',
                'input[type="button"][value*="OK"]',
                'input[value*="次"]',
                'button:has-text("次")',
            ]

            for selector in ok_selectors:
                locator = page.locator(selector)
                count = await locator.count()
                if count > 0:
                    print(f"  ✓ 見つかった: {selector} (数: {count})")
                    try:
                        is_visible = await locator.first.is_visible()
                        is_enabled = await locator.first.is_enabled()
                        value = await locator.first.get_attribute("value")
                        print(f"    - 表示: {is_visible}, 有効: {is_enabled}, value=\"{value}\"")
                    except Exception as e:
                        print(f"    - エラー: {e}")

            # 全てのボタンを再度列挙
            print("\n  OTP画面の全ボタン一覧:")
            all_buttons = await page.locator('button, input[type="button"], input[type="submit"]').all()
            for i, btn in enumerate(all_buttons):
                try:
                    is_visible = await btn.is_visible()
                    if is_visible:
                        tag = await btn.evaluate("el => el.tagName")
                        type_attr = await btn.evaluate("el => el.type")
                        value = await btn.evaluate("el => el.value || el.textContent")
                        name = await btn.evaluate("el => el.name")
                        print(f"    {i+1}. <{tag} type={type_attr} name={name}> \"{value}\"")
                except Exception:
                    pass

            # スクリーンショット保存
            screenshot_path = "screenshots/ex_otp_debug.png"
            os.makedirs("screenshots", exist_ok=True)
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"\nスクリーンショット保存: {screenshot_path}")

            print("\n" + "=" * 70)
            print("60秒間ブラウザを保持します（確認用）")
            print("=" * 70)
            await page.wait_for_timeout(60000)

        except Exception as e:
            print(f"\nエラー: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
