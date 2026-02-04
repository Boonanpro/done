"""
Amazon検索結果のセレクタ調査スクリプト

目的:
1. 検索結果ページのDOM構造を確認
2. スクロール前後での要素数の変化を確認
3. 正しいセレクタを特定
"""

import asyncio
import re
from playwright.async_api import async_playwright

# 調査対象
SEARCH_QUERY = "アベンヌウォーター 50ml 4本"  # ダンが使うであろうクエリ
AMAZON_URL = "https://www.amazon.co.jp/"

# 現在のセレクタ（selectors.pyから）
SELECTORS = {
    "search_box": "#twotabsearchtextbox",
    "search_results": '[data-component-type="s-search-result"]',
    "result_asin": "[data-asin]",
    "result_title": "h2 a span",
    "result_price": ".a-price .a-offscreen",
}


async def investigate():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # 見えるように
        page = await browser.new_page(viewport={"width": 1280, "height": 800})

        print("=" * 60)
        print("Amazon検索結果 セレクタ調査")
        print("=" * 60)

        # 1. Amazonを開く
        print("\n[Step 1] Amazon を開く...")
        await page.goto(AMAZON_URL)
        await page.wait_for_timeout(2000)

        # 2. 検索実行
        print(f"\n[Step 2] 「{SEARCH_QUERY}」を検索...")
        search_box = page.locator(SELECTORS["search_box"])
        if await search_box.count() == 0:
            print("  ❌ 検索ボックスが見つかりません")
            # 他のセレクタを試す
            for alt in ['input[name="field-keywords"]', '#nav-search-bar-form input']:
                if await page.locator(alt).count() > 0:
                    print(f"  → 代替セレクタ発見: {alt}")
                    search_box = page.locator(alt).first
                    break

        await search_box.fill(SEARCH_QUERY)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(3000)

        # 3. スクロール前の状態を確認
        print("\n[Step 3] スクロール前の検索結果を確認...")
        await check_search_results(page, "スクロール前")

        # 4. HTMLを保存（デバッグ用）
        html_before = await page.content()
        with open("amazon_search_before_scroll.html", "w", encoding="utf-8") as f:
            f.write(html_before)
        print("  → HTML保存: amazon_search_before_scroll.html")

        # 5. スクロールテスト
        print("\n[Step 4] スクロールテスト...")
        for i in range(5):
            await page.evaluate("window.scrollBy(0, 500)")
            await page.wait_for_timeout(1000)
            count = await page.locator(SELECTORS["search_results"]).count()
            print(f"  スクロール {i+1}: 検索結果 {count} 件")

        # 6. スクロール後の状態を確認
        print("\n[Step 5] スクロール後の検索結果を確認...")
        await check_search_results(page, "スクロール後")

        # 7. 詳細なDOM調査
        print("\n[Step 6] DOM構造の詳細調査...")
        await investigate_dom_structure(page)

        # 8. 特定商品の検索テスト
        print("\n[Step 7] 「4本」「4個」を含む商品を探す...")
        await find_matching_products(page, ["4本", "4個", "4個セット", "×4"])

        # スクリーンショット
        await page.screenshot(path="amazon_search_investigation.png", full_page=True)
        print("\n→ フルページスクリーンショット保存: amazon_search_investigation.png")

        print("\n" + "=" * 60)
        print("調査完了")
        print("=" * 60)

        # ブラウザを開いたまま待機
        input("\nEnterキーで終了...")
        await browser.close()


async def check_search_results(page, label: str):
    """検索結果の状態を確認"""
    # メインセレクタ
    results = page.locator(SELECTORS["search_results"])
    count = await results.count()
    print(f"  [{label}] search_results: {count} 件")

    # data-asin属性を持つ要素
    asin_elems = page.locator(SELECTORS["result_asin"])
    asin_count = await asin_elems.count()
    print(f"  [{label}] data-asin要素: {asin_count} 件")

    # 有効なASINをカウント
    valid_asins = []
    for i in range(min(asin_count, 30)):
        asin = await asin_elems.nth(i).get_attribute("data-asin")
        if asin and len(asin) == 10 and asin.isalnum():
            valid_asins.append(asin)
    print(f"  [{label}] 有効なASIN: {len(valid_asins)} 件")

    # 最初の5件を表示
    if valid_asins:
        print(f"  [{label}] 最初の5件: {valid_asins[:5]}")


async def investigate_dom_structure(page):
    """DOM構造を詳細に調査"""
    # 様々なセレクタを試す
    test_selectors = [
        '[data-component-type="s-search-result"]',
        '[data-asin]:not([data-asin=""])',
        '.s-result-item',
        '.s-search-result',
        '[data-cel-widget^="search_result_"]',
        '.s-main-slot .s-result-item',
    ]

    print("  セレクタ別の要素数:")
    for sel in test_selectors:
        try:
            count = await page.locator(sel).count()
            print(f"    {sel}: {count} 件")
        except Exception as e:
            print(f"    {sel}: エラー ({e})")


async def find_matching_products(page, keywords: list):
    """特定のキーワードを含む商品を探す"""
    results = page.locator(SELECTORS["search_results"])
    count = await results.count()

    found = []
    for i in range(count):
        elem = results.nth(i)

        # ASIN
        asin = await elem.get_attribute("data-asin")
        if not asin or len(asin) != 10:
            continue

        # タイトル（複数の方法で取得を試みる）
        title = ""

        # 方法1: h2 a span
        title_elem = elem.locator("h2 a span")
        if await title_elem.count() > 0:
            title = await title_elem.first.text_content() or ""

        # 方法2: h2 直下のテキスト
        if not title:
            h2_elem = elem.locator("h2")
            if await h2_elem.count() > 0:
                title = await h2_elem.first.text_content() or ""

        # 方法3: aria-label
        if not title:
            title = await elem.get_attribute("aria-label") or ""

        title = title.strip()

        # キーワードマッチ
        for kw in keywords:
            if kw in title:
                found.append({
                    "index": i + 1,
                    "asin": asin,
                    "title": title[:60],
                    "keyword": kw,
                })
                break

    if found:
        print(f"  マッチした商品: {len(found)} 件")
        for item in found:
            print(f"    [{item['index']}] {item['title']}...")
            print(f"        ASIN: {item['asin']}, キーワード: {item['keyword']}")
    else:
        print(f"  マッチした商品: 0 件")
        print(f"  → キーワード {keywords} を含む商品が見つかりませんでした")

        # タイトル一覧を表示
        print("\n  全商品のタイトル一覧:")
        for i in range(min(count, 10)):
            elem = results.nth(i)
            asin = await elem.get_attribute("data-asin")
            title_elem = elem.locator("h2")
            title = ""
            if await title_elem.count() > 0:
                title = (await title_elem.first.text_content() or "").strip()
            print(f"    [{i+1}] {title[:50]}... (ASIN: {asin})")


if __name__ == "__main__":
    asyncio.run(investigate())
