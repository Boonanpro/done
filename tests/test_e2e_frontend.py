"""E2E Frontend Test - ブラウザを実際に立ち上げてプロジェクトチャットをテスト"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright

async def main():
    print("=== E2E Frontend Test ===")
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        page = await browser.new_page()

        # Step 1: フロントエンドを開く
        print("[1] localhost:3000 を開く...")
        await page.goto("http://localhost:3000", timeout=60000)
        await page.wait_for_load_state("networkidle", timeout=30000)
        await page.screenshot(path="tests/screenshot_01_top.png")
        print("  スクリーンショット保存: screenshot_01_top.png")

        # Step 2: ログインページに移動
        print("[2] ログイン...")
        # ログインフォームを探す
        # メールとパスワードを入力
        email_input = page.locator('input[type="email"], input[name="email"], input[placeholder*="メール"], input[placeholder*="email"]').first
        password_input = page.locator('input[type="password"]').first

        if await email_input.count() > 0:
            await email_input.fill("0aw325171@gmail.com")
            await password_input.fill("Bold1315")
            # ログインボタンをクリック
            login_btn = page.locator('button[type="submit"], button:has-text("ログイン"), button:has-text("Login")').first
            await login_btn.click()
            await page.wait_for_load_state("networkidle")
            print("  ログイン情報を入力して送信")
        else:
            print("  ログインフォームが見つからない - 既にログイン済みかも")

        await asyncio.sleep(2)
        await page.screenshot(path="tests/screenshot_02_after_login.png")
        print("  スクリーンショット保存: screenshot_02_after_login.png")

        # Step 3: プロジェクトチャットを探す
        print("[3] プロジェクトチャットへ移動...")
        # SDK E2E Test プロジェクトを探す
        project_link = page.locator('text=SDK E2E Test').first
        if await project_link.count() > 0:
            await project_link.click()
            await asyncio.sleep(2)
        else:
            print("  'SDK E2E Test' が見つからない、ページ構造を確認")
            await page.screenshot(path="tests/screenshot_03_no_project.png")

        await page.screenshot(path="tests/screenshot_03_project.png")
        print("  スクリーンショット保存: screenshot_03_project.png")

        # Step 4: メッセージ送信
        print("[4] メッセージ送信...")
        textarea = page.locator('textarea, input[type="text"]').last
        if await textarea.count() > 0:
            await textarea.fill("example.comを開いて、ページの内容を教えてください。")
            # 送信ボタンまたはEnter
            send_btn = page.locator('button[type="submit"], button:has-text("送信"), button[aria-label*="send"]').last
            if await send_btn.count() > 0:
                await send_btn.click()
            else:
                await textarea.press("Enter")
            print("  メッセージ送信完了")
        else:
            print("  テキスト入力欄が見つからない")

        # Step 5: 応答を待つ
        print("[5] 応答を待機中（最大120秒）...")
        for i in range(24):
            await asyncio.sleep(5)
            await page.screenshot(path=f"tests/screenshot_04_wait_{i}.png")
            print(f"  {(i+1)*5}秒経過... screenshot_04_wait_{i}.png")

            # ダンの応答が表示されたか確認
            dan_messages = page.locator('[class*="ai"], [class*="dan"], [data-sender="ai"]')
            count = await dan_messages.count()
            if count > 0:
                last_msg = await dan_messages.last.text_content()
                if last_msg and len(last_msg) > 20:
                    print(f"  応答検出: {last_msg[:200]}")
                    break

        await page.screenshot(path="tests/screenshot_05_final.png")
        print("  最終スクリーンショット: screenshot_05_final.png")

        print()
        print("ブラウザを30秒間開いたままにします（手動確認用）...")
        await asyncio.sleep(30)

        await browser.close()

    print()
    print("=== Test Complete ===")

if __name__ == "__main__":
    asyncio.run(main())
