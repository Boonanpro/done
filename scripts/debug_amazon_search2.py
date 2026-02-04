"""
Amazon検索デバッグ v2 - ボット検知対応版
"""

import asyncio
import sys
sys.path.insert(0, "D:\\done")

from playwright.async_api import async_playwright


async def debug_amazon_search():
    output_lines = []

    def log(msg):
        print(msg.encode('cp932', errors='replace').decode('cp932'))
        output_lines.append(msg)

    log("=" * 70)
    log("Amazon検索デバッグ v2")
    log("=" * 70)

    async with async_playwright() as p:
        # ユーザーデータディレクトリを使用してボット検知を回避
        browser = await p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        query = "アベンヌウォーター 50ml 4本"
        log(f"\n[1] 検索クエリ: {query}")

        # Amazonにアクセス
        log("[1] Amazonにアクセス中...")
        await page.goto("https://www.amazon.co.jp/")
        await page.wait_for_timeout(5000)

        # 現在のページ状態を確認
        current_url = page.url
        log(f"[1] URL: {current_url}")

        # スクリーンショットを保存
        await page.screenshot(path="amazon_debug_landing.png")
        log("[1] amazon_debug_landing.png 保存")

        # ボット検知チェック
        search_selectors = [
            'input[name="field-keywords"]:not([type="hidden"])',
            '#twotabsearchtextbox',
            'input[id="twotabsearchtextbox"]',
            '#nav-search input[type="text"]',
        ]

        search_box = None
        for selector in search_selectors:
            locator = page.locator(selector)
            if await locator.count() > 0:
                search_box = locator
                log(f"[1] 検索ボックス発見: {selector}")
                break

        if search_box is None:
            log("[1] 検索ボックスが見つかりません")
            log("[1] ボット検知ページをチェック...")

            # 続行ボタンを探す
            continue_selectors = [
                'input[type="submit"]',
                'button[type="submit"]',
                'a.a-button',
            ]
            for selector in continue_selectors:
                btn = page.locator(selector)
                if await btn.count() > 0:
                    log(f"[1] ボタン発見: {selector}")
                    await btn.first.click()
                    await page.wait_for_timeout(3000)
                    break

            # 再度検索ボックスを探す
            for selector in search_selectors:
                locator = page.locator(selector)
                if await locator.count() > 0:
                    search_box = locator
                    log(f"[1] 検索ボックス発見（リトライ後）: {selector}")
                    break

        if search_box is None:
            log("[1] ERROR: 検索ボックスが見つかりません。手動で操作してください。")
            log("[1] 30秒待機します...")
            await page.wait_for_timeout(30000)

            # 再度試行
            for selector in search_selectors:
                locator = page.locator(selector)
                if await locator.count() > 0:
                    search_box = locator
                    log(f"[1] 検索ボックス発見（手動後）: {selector}")
                    break

        if search_box is None:
            log("[1] FATAL: 検索ボックスが見つかりません")
            await browser.close()
            return

        # 検索実行
        log(f"[2] 検索実行: {query}")
        await search_box.fill(query)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(5000)

        log(f"[2] URL: {page.url}")
        await page.screenshot(path="amazon_debug_search_result.png")
        log("[2] amazon_debug_search_result.png 保存")

        # セレクタ確認
        log("\n[3] セレクタ別マッチ数:")
        selectors = [
            '[data-component-type="s-search-result"]',
            '[data-asin]',
            '.s-result-item',
        ]
        for sel in selectors:
            count = await page.locator(sel).count()
            log(f"    {sel}: {count}件")

        # 商品取得
        log("\n[4] 商品取得:")
        js_code = """
        () => {
            const results = [];
            const elements = document.querySelectorAll('[data-component-type="s-search-result"]');

            for (const elem of elements) {
                const asin = elem.getAttribute('data-asin');
                if (!asin || asin.length !== 10) continue;

                let title = '';
                const titleSelectors = ['h2 a span', '.a-text-normal', 'h2 span'];
                for (const sel of titleSelectors) {
                    const el = elem.querySelector(sel);
                    if (el && el.textContent) {
                        title = el.textContent.trim();
                        break;
                    }
                }

                let price = null;
                const priceEl = elem.querySelector('.a-price .a-offscreen');
                if (priceEl) {
                    const match = priceEl.textContent.match(/[￥¥]?([0-9,]+)/);
                    if (match) {
                        price = parseInt(match[1].replace(/,/g, ''), 10);
                    }
                }

                results.push({
                    asin: asin,
                    title: title.substring(0, 100),
                    price: price
                });
            }

            return results;
        }
        """

        products = await page.evaluate(js_code)
        log(f"    取得件数: {len(products)}件")

        log("\n[5] 商品一覧:")
        for i, p in enumerate(products, 1):
            title = p['title']
            has_50 = '50' in title
            has_4 = '4本' in title or '4個' in title or '×4' in title
            marker = ""
            if has_50 and has_4:
                marker = " *** TARGET ***"
            elif has_50:
                marker = " * 50含む"
            elif has_4:
                marker = " * 4本含む"

            price = f"Y{p['price']:,}" if p['price'] else "不明"
            log(f"    {i:2}. [{p['asin']}] {title[:60]}... | {price}{marker}")

        # フィルタ
        log("\n[6] フィルタ結果:")
        with_50 = [p for p in products if '50' in p['title']]
        with_4 = [p for p in products if '4本' in p['title'] or '4個' in p['title'] or '×4' in p['title']]
        with_both = [p for p in products if '50' in p['title'] and ('4本' in p['title'] or '4個' in p['title'] or '×4' in p['title'])]

        log(f"    50含む: {len(with_50)}件")
        log(f"    4本含む: {len(with_4)}件")
        log(f"    両方: {len(with_both)}件")

        if with_both:
            log("\n    *** 該当商品 ***")
            for p in with_both:
                log(f"    - {p['title']} | ASIN: {p['asin']}")

        # 結論
        log("\n" + "=" * 70)
        log("結論")
        log("=" * 70)
        if len(with_both) > 0:
            log("50ml 4本セットは取得できている")
            log("問題はLLM側にある可能性")
        else:
            log("50ml 4本セットが取得できていない")
            log("セレクタまたはタイトル抽出に問題がある可能性")

        # 保存
        with open("amazon_debug_result.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(output_lines))

        log("\n結果を保存しました。10秒後に閉じます...")
        await page.wait_for_timeout(10000)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(debug_amazon_search())
