"""
Amazon検索 - ブラウザを開いたまま待機
"""

import asyncio
import sys
sys.path.insert(0, "D:\\done")

from playwright.async_api import async_playwright


async def main():
    print("Amazon検索を実行し、ブラウザを開いたまま待機します")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = await context.new_page()

        query = "アベンヌウォーター 50ml 4本"
        print(f"検索クエリ: {query}")

        await page.goto("https://www.amazon.co.jp/")
        await page.wait_for_timeout(5000)

        # ボット検知対応
        search_box = page.locator('input[name="field-keywords"]:not([type="hidden"])')
        if await search_box.count() == 0:
            btn = page.locator('button[type="submit"]')
            if await btn.count() > 0:
                await btn.first.click()
                await page.wait_for_timeout(3000)
            search_box = page.locator('input[name="field-keywords"]:not([type="hidden"])')

        if await search_box.count() > 0:
            await search_box.fill(query)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(5000)
            print("検索完了")
        else:
            print("ERROR: 検索ボックスが見つからない")

        print(f"URL: {page.url}")
        print("")
        print("=" * 50)
        print("ブラウザを開いたまま2分間待機しています")
        print("画面を確認してください")
        print("=" * 50)

        # 2分待機
        await page.wait_for_timeout(120000)

        await browser.close()
        print("ブラウザを閉じました")


if __name__ == "__main__":
    asyncio.run(main())
