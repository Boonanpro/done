"""
Amazon全商品要素を取得（広告含む）
"""

import asyncio
import sys
sys.path.insert(0, "D:\\done")

from playwright.async_api import async_playwright


async def debug_all_products():
    output_lines = []

    def log(msg):
        print(msg.encode('cp932', errors='replace').decode('cp932'))
        output_lines.append(msg)

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
        log(f"検索: {query}")

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
        else:
            log("ERROR: 検索ボックスが見つからない")
            await browser.close()
            return

        log(f"URL: {page.url}")

        # 全ての data-asin 要素を取得
        log("\n=== 全 data-asin 要素 ===")

        all_asin_js = """
        () => {
            const results = [];
            const elements = document.querySelectorAll('[data-asin]');

            for (const elem of elements) {
                const asin = elem.getAttribute('data-asin');
                if (!asin || asin.length < 5) continue;

                const componentType = elem.getAttribute('data-component-type') || 'unknown';

                // タイトル取得（複数セレクタ試行）
                let title = '';
                const titleSelectors = [
                    'h2 a span',
                    '.a-text-normal',
                    'h2 span',
                    '.a-link-normal span',
                    '[data-cy="title-recipe"] span',
                    'a[href*="/dp/"] span'
                ];
                for (const sel of titleSelectors) {
                    const el = elem.querySelector(sel);
                    if (el && el.textContent && el.textContent.trim().length > 5) {
                        title = el.textContent.trim();
                        break;
                    }
                }

                // 価格
                let price = null;
                const priceEl = elem.querySelector('.a-price .a-offscreen, .a-price-whole');
                if (priceEl) {
                    const match = priceEl.textContent.match(/[￥¥]?([0-9,]+)/);
                    if (match) {
                        price = parseInt(match[1].replace(/,/g, ''), 10);
                    }
                }

                // 広告かどうか
                const isAd = elem.closest('[data-component-type="sp-sponsored-result"]') !== null ||
                             elem.textContent.includes('スポンサー');

                results.push({
                    asin: asin,
                    componentType: componentType,
                    title: title.substring(0, 100),
                    price: price,
                    isAd: isAd
                });
            }

            return results;
        }
        """

        all_products = await page.evaluate(all_asin_js)
        log(f"全要素数: {len(all_products)}件")

        # 重複除去
        seen = set()
        unique_products = []
        for p in all_products:
            if p['asin'] not in seen and p['title']:
                seen.add(p['asin'])
                unique_products.append(p)

        log(f"重複除去後: {len(unique_products)}件")

        # 「4本」を含む商品を探す
        log("\n=== 「4本」「4個」「×4」を含む商品 ===")
        products_with_4 = [p for p in unique_products if '4本' in p['title'] or '4個' in p['title'] or '×4' in p['title'] or 'x4' in p['title'].lower()]

        if products_with_4:
            for p in products_with_4:
                ad_mark = "[広告]" if p['isAd'] else ""
                log(f"  {ad_mark}[{p['asin']}] {p['title'][:70]}...")
        else:
            log("  該当商品なし")

        # 全商品リスト
        log("\n=== 全商品リスト ===")
        for i, p in enumerate(unique_products, 1):
            title = p['title']
            has_50 = '50' in title
            has_4 = '4本' in title or '4個' in title or '×4' in title
            marker = ""
            if has_50 and has_4:
                marker = " *** TARGET ***"
            elif has_4:
                marker = " ** 4本含む **"
            elif has_50:
                marker = " * 50含む"

            ad_mark = "[AD]" if p['isAd'] else ""
            price = f"Y{p['price']:,}" if p['price'] else "不明"
            ct = p['componentType'][:20] if p['componentType'] else ""
            log(f"  {i:2}. {ad_mark}[{p['asin']}][{ct}] {title[:50]}... | {price}{marker}")

        # 結論
        log("\n=== 結論 ===")
        products_with_4_count = len(products_with_4)
        if products_with_4_count > 0:
            log(f"「4本」を含む商品が {products_with_4_count} 件見つかりました")
        else:
            log("「4本」を含む商品は見つかりませんでした")
            log("ユーザーが見ている商品は、現在の検索結果には存在しない可能性があります")

        # 保存
        with open("amazon_debug_all_products.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(output_lines))

        log("\n結果を amazon_debug_all_products.txt に保存しました")
        log("10秒後に閉じます...")
        await page.wait_for_timeout(10000)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(debug_all_products())
