"""
SmartEX OTP画面のセレクタを確認するスクリプト

実際のサイトでログイン→OTP画面まで進み、
「閉じる」ボタンやOTP入力フィールドのセレクタを確認する
"""
import asyncio
import os
from playwright.async_api import async_playwright
from dotenv import load_dotenv

# .envファイルを読み込み
load_dotenv()

# 認証情報を環境変数から取得
MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")

# URLとセレクタ
LOGIN_URL = "https://shinkansen2.jr-central.co.jp/RSV_P/smart_index.htm"

async def main():
    print("=== SmartEX OTP画面セレクタ確認 ===\n")

    if not MEMBER_ID or not PASSWORD:
        print("エラー: 環境変数 SMARTEX_MEMBER_ID と SMARTEX_PASSWORD を設定してください")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=1000)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="ja-JP",
        )
        page = await context.new_page()

        try:
            # Step 1: ログインページにアクセス
            print(f"1. ログインページにアクセス: {LOGIN_URL}")
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # Step 2: ログイン情報入力
            print("2. 会員IDとパスワードを入力")
            await page.locator('role=textbox[name="会員ID"]').fill(MEMBER_ID)
            await page.wait_for_timeout(500)
            await page.locator('role=textbox[name="パスワード"]').fill(PASSWORD)
            await page.wait_for_timeout(500)

            # Step 3: ログインボタンをクリック
            print("3. ログインボタンをクリック")
            await page.locator('role=button[name="ログイン"]').click()

            # ページ遷移を待機
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(3000)

            print(f"\n現在のURL: {page.url}\n")

            # Step 4: OTP画面かどうか確認
            print("4. OTP画面の要素を確認中...\n")

            # ページのHTML構造を確認
            print("--- ページタイトル ---")
            title = await page.title()
            print(f"  {title}")

            print("\n--- 「自動音声案内発信」ボタン ---")
            send_button = page.locator('input[value="自動音声案内発信"]')
            count = await send_button.count()
            print(f"  見つかった数: {count}")
            if count > 0:
                is_visible = await send_button.is_visible()
                print(f"  表示されている: {is_visible}")

            print("\n--- 「閉じる」ボタンを探す ---")
            # 複数の候補を試す
            close_selectors = [
                'button:has-text("閉じる")',
                'input[value="閉じる"]',
                'a:has-text("閉じる")',
                '[onclick*="close"]',
                'button[type="button"]:has-text("閉じる")',
                'input[type="button"][value="閉じる"]',
            ]

            for selector in close_selectors:
                locator = page.locator(selector)
                count = await locator.count()
                if count > 0:
                    print(f"  ✓ 見つかった: {selector}")
                    print(f"    数: {count}")
                    try:
                        is_visible = await locator.first.is_visible()
                        print(f"    表示: {is_visible}")
                        text = await locator.first.text_content()
                        print(f"    テキスト: {text}")
                    except Exception as e:
                        print(f"    エラー: {e}")

            print("\n--- OTP入力フィールド ---")
            otp_selectors = [
                'input[type="tel"]',
                'input[name*="otp"]',
                'input[name*="password"]',
                'input[maxlength="6"]',
            ]

            for selector in otp_selectors:
                locator = page.locator(selector)
                count = await locator.count()
                if count > 0:
                    print(f"  ✓ 見つかった: {selector}")
                    print(f"    数: {count}")
                    try:
                        is_visible = await locator.first.is_visible()
                        is_enabled = await locator.first.is_enabled()
                        print(f"    表示: {is_visible}, 有効: {is_enabled}")
                    except Exception as e:
                        print(f"    エラー: {e}")

            print("\n--- OKボタン ---")
            ok_selectors = [
                'input[value*="OK"]',
                'button:has-text("OK")',
                'input[type="submit"]',
            ]

            for selector in ok_selectors:
                locator = page.locator(selector)
                count = await locator.count()
                if count > 0:
                    print(f"  ✓ 見つかった: {selector}")
                    print(f"    数: {count}")
                    try:
                        is_visible = await locator.first.is_visible()
                        is_enabled = await locator.first.is_enabled()
                        print(f"    表示: {is_visible}, 有効: {is_enabled}")
                    except Exception as e:
                        print(f"    エラー: {e}")

            # 全てのボタンを一覧表示
            print("\n--- ページ内の全ボタン ---")
            all_buttons = await page.locator('button, input[type="button"], input[type="submit"]').all()
            for i, btn in enumerate(all_buttons):
                try:
                    tag = await btn.evaluate("el => el.tagName")
                    type_attr = await btn.evaluate("el => el.type")
                    value = await btn.evaluate("el => el.value || el.textContent")
                    is_visible = await btn.is_visible()
                    print(f"  {i+1}. <{tag} type={type_attr}> value/text=\"{value}\" visible={is_visible}")
                except Exception:
                    pass

            print("\n--- スクリーンショット保存 ---")
            screenshot_path = "screenshots/ex_otp_screen.png"
            os.makedirs("screenshots", exist_ok=True)
            await page.screenshot(path=screenshot_path)
            print(f"  保存: {screenshot_path}")

            print("\n\n=== 待機中（60秒） ===")
            print("ブラウザを確認して、必要に応じて手動で操作してください")
            await page.wait_for_timeout(60000)

        except Exception as e:
            print(f"\nエラー: {e}")
            import traceback
            traceback.print_exc()

            # エラー時もスクリーンショット
            try:
                screenshot_path = "screenshots/ex_otp_error.png"
                os.makedirs("screenshots", exist_ok=True)
                await page.screenshot(path=screenshot_path)
                print(f"エラー画面を保存: {screenshot_path}")
            except Exception:
                pass

        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
