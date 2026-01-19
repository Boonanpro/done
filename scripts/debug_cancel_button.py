"""
キャンセル確認画面の実行ボタンをデバッグ
"""
import asyncio
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from app.utils.session_manager import SessionManager


async def main():
    session_mgr = SessionManager("smartex_cancel_test")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # セッションから復元されるのでログイン済みのはず
            await page.goto("https://expy.jp")
            await page.wait_for_timeout(3000)

            # 確認画面のHTMLを保存
            html_content = await page.content()
            with open("debug_cancel_confirm.html", "w", encoding="utf-8") as f:
                f.write(html_content)

            print("HTML saved to debug_cancel_confirm.html")

            # 実行ボタンを探す
            print("\n=== Looking for execute button ===")

            selectors = [
                'input[name="b2"][type="submit"]',
                'input[type="submit"][value*="払戻"]',
                'input[value*="OK"]',
                'button:has-text("OK")',
            ]

            for selector in selectors:
                elements = page.locator(selector)
                count = await elements.count()
                print(f"{selector}: {count} elements")

                if count > 0:
                    for i in range(count):
                        elem = elements.nth(i)
                        try:
                            value = await elem.get_attribute("value")
                            name = await elem.get_attribute("name")
                            id_attr = await elem.get_attribute("id")
                            print(f"  [{i}] value={value}, name={name}, id={id_attr}")
                        except:
                            pass

            await page.wait_for_timeout(60000)

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
