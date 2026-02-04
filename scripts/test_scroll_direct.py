"""
スクロール動作テスト - 検索結果URLに直接アクセス
"""

import asyncio
import sys
sys.path.insert(0, "D:/done")

from app.tools.browser import get_executor_page, close_executor_browser


async def test_scroll_direct():
    print("=" * 60)
    print("スクロールテスト（直接URL）")
    print("=" * 60)

    page = await get_executor_page()

    # 検索結果URLに直接アクセス
    search_url = "https://www.amazon.co.jp/s?k=アベンヌウォーター"
    print(f"\n1. 検索結果ページを直接開きます: {search_url}")
    await page.goto(search_url)
    print("   → 5秒待機")
    await page.wait_for_timeout(5000)

    # 現在のURLを確認
    current_url = await page.evaluate("window.location.href")
    print(f"   現在のURL: {current_url[:100]}...")

    # ページの高さを確認
    page_height = await page.evaluate("document.body.scrollHeight")
    viewport_height = await page.evaluate("window.innerHeight")
    print(f"   ページ高さ: {page_height}px, ビューポート: {viewport_height}px")

    # スクロールテスト
    for i in range(5):
        print(f"\n2-{i+1}. スクロールします（600px下へ）...")

        scroll_before = await page.evaluate("window.scrollY")
        print(f"   スクロール前: {scroll_before}px")

        # スクロール実行
        result = await page.evaluate("window.scrollBy(0, 600); window.scrollY")
        print(f"   evaluate結果: {result}")

        scroll_after = await page.evaluate("window.scrollY")
        print(f"   スクロール後: {scroll_after}px")
        print(f"   差分: {scroll_after - scroll_before}px")

        print("   → 3秒待機（目視確認）")
        await page.wait_for_timeout(3000)

    print("\n" + "=" * 60)
    print("10秒後にブラウザを閉じます...")
    await page.wait_for_timeout(10000)
    await close_executor_browser()


if __name__ == "__main__":
    asyncio.run(test_scroll_direct())
