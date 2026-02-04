"""
Amazon Executor v2 テスト

新しいエグゼキューターの動作確認。
"""

import asyncio
import sys
sys.path.insert(0, "D:/done")

from app.executors.amazon.executor import AmazonExecutor


async def test_search():
    """検索機能のテスト"""
    print("=" * 60)
    print("Amazon Executor v2 テスト")
    print("=" * 60)

    # まずページを取得してデバッグ
    from app.tools.browser import get_executor_page
    page = await get_executor_page()

    print("\n[デバッグ] Amazon を開いてスクリーンショットを取得...")
    await page.goto("https://www.amazon.co.jp/", timeout=30000)
    await page.wait_for_timeout(5000)

    # スクリーンショット
    await page.screenshot("amazon_debug.png")
    print("  → amazon_debug.png に保存")

    # 現在のURL
    current_url = page.url
    print(f"  現在のURL: {current_url}")

    # HTML内容を確認
    html = await page.content()
    print(f"  HTML長さ: {len(html)} 文字")

    # 検索ボックスの確認
    search_box = page.locator("#twotabsearchtextbox")
    count = await search_box.count()
    print(f"  検索ボックス (#twotabsearchtextbox): {count}個")

    if count == 0:
        # 他のセレクタを試す
        alt_selectors = [
            'input[name="field-keywords"]',
            '#nav-search-bar-form input[type="text"]',
            'input[type="text"][placeholder*="検索"]',
        ]
        for sel in alt_selectors:
            c = await page.locator(sel).count()
            print(f"  {sel}: {c}個")

    executor = AmazonExecutor()

    # テスト1: 検索
    print("\n[テスト1] 検索: アベンヌウォーター 50ml")
    result = await executor._do_search({
        "query": "アベンヌウォーター 50ml"
    })

    print(f"Success: {result.success}")
    print(f"Options count: {len(result.options)}")

    # 結果をファイルに出力
    with open("amazon_test_result.txt", "w", encoding="utf-8") as f:
        f.write(f"Success: {result.success}\n")
        f.write(f"Options: {len(result.options)}\n\n")
        f.write("Message:\n")
        f.write(result.message or "None")
        f.write("\n\n")
        if result.options:
            f.write("First 3 products:\n")
            for i, opt in enumerate(result.options[:3], 1):
                f.write(f"{i}. {opt.title}\n")
                f.write(f"   Price: {opt.price}\n")
                f.write(f"   ASIN: {opt.details.get('asin')}\n\n")

    print("  -> Results saved to amazon_test_result.txt")

    return result


async def test_add_to_cart(asin: str):
    """カート追加のテスト"""
    print("\n" + "=" * 60)
    print(f"[テスト2] カート追加: ASIN={asin}")
    print("=" * 60)

    executor = AmazonExecutor()

    result = await executor.add_to_cart({
        "asin": asin,
        "quantity": 1
    })

    print(f"成功: {result.success}")
    print(f"メッセージ: {result.message}")

    return result


async def main():
    # 検索テスト
    search_result = await test_search()

    if search_result.success and search_result.options:
        # 最初の商品でカート追加テスト
        first_asin = search_result.options[0].details.get("asin")

        print("\n" + "-" * 60)
        print(f"カート追加テストを実行しますか？ (ASIN: {first_asin})")
        print("※ 実際にカートに追加されます")
        print("-" * 60)

        # 自動実行しない（手動確認が必要な場合はコメントアウト）
        # await test_add_to_cart(first_asin)


if __name__ == "__main__":
    asyncio.run(main())
