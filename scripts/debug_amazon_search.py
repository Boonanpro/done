"""
Amazon検索の徹底デバッグ

問題:
1. スクロールしていない
2. 商品が正しく取得できていない
3. 50ml 4本セットが見つからないと言っている

調査項目:
1. 検索後のDOM構造
2. セレクタで何件マッチするか
3. 取得した商品タイトル一覧
4. 広告と通常商品の違い
"""

import asyncio
import sys
sys.path.insert(0, "D:\\done")

from playwright.async_api import async_playwright


async def debug_amazon_search():
    # 結果をファイルに出力
    output_lines = []

    def log(msg):
        print(msg.encode('cp932', errors='replace').decode('cp932'))
        output_lines.append(msg)

    log("=" * 70)
    log("Amazon検索デバッグ")
    log("=" * 70)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # 1. Amazonで検索
        query = "アベンヌウォーター 50ml 4本"
        log(f"\n[1] 検索クエリ: {query}")

        await page.goto("https://www.amazon.co.jp/")
        await page.wait_for_timeout(3000)

        # 検索ボックスに入力
        search_box = page.locator('input[name="field-keywords"]:not([type="hidden"])')
        if await search_box.count() > 0:
            await search_box.fill(query)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(5000)
            log("[1] 検索完了")
        else:
            log("[1] ERROR: 検索ボックスが見つからない")
            await browser.close()
            return

        # 2. 検索結果ページのURL確認
        log(f"\n[2] 現在のURL: {page.url}")

        # 3. セレクタで商品要素を取得
        log("\n[3] セレクタ別のマッチ数:")

        selectors_to_test = [
            '[data-component-type="s-search-result"]',
            '[data-asin]',
            '.s-result-item',
            '.s-search-result',
            '[data-cel-widget^="search_result"]',
        ]

        for selector in selectors_to_test:
            count = await page.locator(selector).count()
            log(f"    {selector}: {count}件")

        # 4. 実際の商品情報を取得（現在のExecutorと同じロジック）
        log("\n[4] Executor方式での商品取得:")

        js_code = """
        () => {
            const results = [];
            const elements = document.querySelectorAll('[data-component-type="s-search-result"]');

            console.log('Found elements:', elements.length);

            for (const elem of elements) {
                const asin = elem.getAttribute('data-asin');
                if (!asin || asin.length !== 10) continue;

                // タイトル取得
                let title = '';
                const titleSelectors = ['h2 a span', '.a-text-normal'];
                for (const sel of titleSelectors) {
                    const el = elem.querySelector(sel);
                    if (el && el.textContent) {
                        title = el.textContent.trim();
                        break;
                    }
                }

                // 価格取得
                let price = null;
                const priceEl = elem.querySelector('.a-price .a-offscreen');
                if (priceEl) {
                    const match = priceEl.textContent.match(/[￥¥]?([0-9,]+)/);
                    if (match) {
                        price = parseInt(match[1].replace(/,/g, ''), 10);
                    }
                }

                if (title) {
                    results.push({
                        asin: asin,
                        title: title.substring(0, 100),
                        price: price,
                        hasTitle: !!title,
                        hasPrice: !!price
                    });
                }
            }

            return results;
        }
        """

        products = await page.evaluate(js_code)
        log(f"    取得件数: {len(products)}件")

        # 5. 取得した商品一覧を表示
        log("\n[5] 取得した商品一覧:")
        for i, p in enumerate(products, 1):
            title = p['title']
            # 50mlや4本が含まれているかチェック
            has_50ml = '50' in title.lower()
            has_4 = '4本' in title or '4個' in title or '×4' in title or 'x4' in title.lower()
            marker = ""
            if has_50ml and has_4:
                marker = " *** 50ml 4本発見! ***"
            elif has_50ml:
                marker = " * 50ml含む"
            elif has_4:
                marker = " * 4本含む"

            price_str = f"Y{p['price']:,}" if p['price'] else "価格不明"
            log(f"    {i:2}. [{p['asin']}] {title[:70]}... | {price_str}{marker}")

        # 6. 「50ml」「4本」を含む商品を検索
        log("\n[6] フィルタ結果:")
        products_with_50ml = [p for p in products if '50' in p['title'].lower()]
        products_with_4 = [p for p in products if '4本' in p['title'] or '4個' in p['title'] or '×4' in p['title'] or 'x4' in p['title'].lower()]
        products_with_both = [p for p in products if '50' in p['title'].lower() and ('4本' in p['title'] or '4個' in p['title'] or '×4' in p['title'] or 'x4' in p['title'].lower())]

        log(f"    '50'を含む商品: {len(products_with_50ml)}件")
        log(f"    '4本/4個/x4'を含む商品: {len(products_with_4)}件")
        log(f"    両方を含む商品: {len(products_with_both)}件")

        if products_with_both:
            log("\n    両方を含む商品:")
            for p in products_with_both:
                log(f"      - {p['title'][:70]}... | ASIN: {p['asin']}")

        # 7. 画面に見える商品をスクリーンショットで確認
        log("\n[7] スクリーンショット保存...")
        await page.screenshot(path="amazon_debug_before_scroll.png", full_page=False)
        log("    amazon_debug_before_scroll.png (スクロール前)")

        # 8. 手動でスクロールして追加商品を確認
        log("\n[8] スクロールして追加確認...")
        for i in range(3):
            await page.evaluate("window.scrollBy(0, 800)")
            await page.wait_for_timeout(1000)
            log(f"    スクロール {i+1}/3 完了")

        # スクロール後に再取得
        products_after_scroll = await page.evaluate(js_code)
        log(f"\n    スクロール後の取得件数: {len(products_after_scroll)}件")

        new_products = [p for p in products_after_scroll if p['asin'] not in [x['asin'] for x in products]]
        log(f"    新規に見つかった商品: {len(new_products)}件")

        if new_products:
            log("\n    新規商品:")
            for p in new_products[:10]:
                log(f"      - {p['title'][:70]}... | ASIN: {p['asin']}")

        await page.screenshot(path="amazon_debug_after_scroll.png", full_page=False)
        log("    amazon_debug_after_scroll.png (スクロール後)")

        # 9. 広告商品の確認
        log("\n[9] 広告商品の確認:")

        ad_js = """
        () => {
            const ads = [];
            // 広告ラベルを持つ要素を探す
            const adLabels = document.querySelectorAll('[data-component-type="sp-sponsored-result"]');
            for (const elem of adLabels) {
                const asin = elem.getAttribute('data-asin');
                const titleEl = elem.querySelector('h2 a span');
                const title = titleEl ? titleEl.textContent.trim() : 'タイトル不明';
                ads.push({ asin, title: title.substring(0, 70) });
            }
            return ads;
        }
        """

        ads = await page.evaluate(ad_js)
        log(f"    広告商品数: {len(ads)}件")
        for ad in ads[:5]:
            log(f"      - [{ad['asin']}] {ad['title']}...")

        # 10. 全要素の data-component-type を調査
        log("\n[10] data-component-type の種類:")

        component_types_js = """
        () => {
            const types = {};
            document.querySelectorAll('[data-component-type]').forEach(el => {
                const type = el.getAttribute('data-component-type');
                types[type] = (types[type] || 0) + 1;
            });
            return types;
        }
        """
        component_types = await page.evaluate(component_types_js)
        for ct, count in component_types.items():
            log(f"    {ct}: {count}件")

        # 11. ページ全体のHTMLを保存（詳細分析用）
        log("\n[11] HTML保存...")
        html = await page.content()
        with open("amazon_debug_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        log("    amazon_debug_page.html に保存")

        # 12. 結論
        log("\n" + "=" * 70)
        log("調査結果サマリー")
        log("=" * 70)
        log(f"検索クエリ: {query}")
        log(f"取得商品数: {len(products)}件")
        log(f"'50'を含む商品: {len(products_with_50ml)}件")
        log(f"'4本'等を含む商品: {len(products_with_4)}件")
        log(f"'50ml 4本'両方に該当: {len(products_with_both)}件")

        if len(products_with_both) == 0:
            log("\n!!! 問題: 50ml 4本セットがExecutor方式で取得できていない !!!")
            log("   原因候補:")
            log("   - セレクタが特定の商品を除外している")
            log("   - タイトル抽出に失敗している")
            log("   - 商品がDOM上の別の場所にある")
            log("   - 広告として別扱いされている")
        else:
            log("\n[OK] 50ml 4本セットは取得できている")
            log("   問題はLLMへの伝達か、LLMの判断にある可能性")

        # 結果をファイルに保存
        with open("amazon_debug_result.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(output_lines))
        log("\n結果を amazon_debug_result.txt に保存しました")

        log("\n画面を確認してください。10秒後に閉じます...")
        await page.wait_for_timeout(10000)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(debug_amazon_search())
