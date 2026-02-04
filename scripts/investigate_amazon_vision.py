"""
Amazon検索結果ページの調査スクリプト

目的：
- 視覚ベースのアプローチで商品を選択するために必要な情報を収集
- 商品カードのクリック可能な領域を特定
- スクリーンショットと商品位置の対応を確認

調査項目：
1. 検索結果の商品カード構造
2. 各商品のクリック可能領域（座標）
3. スクリーンショットでの見た目
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright


async def investigate_amazon_search():
    """Amazon検索結果ページを調査"""

    query = "アベンヌウォーター"
    output_dir = Path("D:/done/amazon_investigation")
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ja-JP",
        )
        page = await context.new_page()

        print(f"1. Amazonを開きます...")
        await page.goto("https://www.amazon.co.jp")
        await page.wait_for_timeout(3000)

        # 検索
        print(f"2. 「{query}」を検索します...")
        search_box = page.locator("#twotabsearchtextbox")
        await search_box.fill(query)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(5000)

        # スクリーンショット（スクロール前）
        print("3. スクリーンショットを撮影（スクロール前）...")
        await page.screenshot(
            path=str(output_dir / f"search_result_{timestamp}_scroll0.png"),
            full_page=False
        )

        # 商品カードの情報を収集
        print("4. 商品カードの情報を収集...")

        # 方法1: data-component-type="s-search-result" を持つ要素
        products_info = await page.evaluate("""
        () => {
            const results = [];
            const items = document.querySelectorAll('[data-component-type="s-search-result"]');

            items.forEach((item, index) => {
                const asin = item.getAttribute('data-asin');
                if (!asin || asin.length !== 10) return;

                const rect = item.getBoundingClientRect();

                // タイトル要素
                const titleEl = item.querySelector('h2 a span, .a-text-normal');
                const titleLinkEl = item.querySelector('h2 a');

                // 画像
                const imgEl = item.querySelector('.s-image');
                const imgRect = imgEl ? imgEl.getBoundingClientRect() : null;

                // 価格
                const priceEl = item.querySelector('.a-price .a-offscreen');
                const priceText = priceEl ? priceEl.textContent : null;

                // クリック可能なリンク
                const linkEls = item.querySelectorAll('a[href*="/dp/"]');
                const links = Array.from(linkEls).map(link => {
                    const linkRect = link.getBoundingClientRect();
                    return {
                        href: link.href,
                        text: link.textContent?.trim().substring(0, 50),
                        rect: {
                            x: linkRect.x,
                            y: linkRect.y,
                            width: linkRect.width,
                            height: linkRect.height,
                            center_x: linkRect.x + linkRect.width / 2,
                            center_y: linkRect.y + linkRect.height / 2
                        }
                    };
                });

                results.push({
                    index: index,
                    asin: asin,
                    title: titleEl ? titleEl.textContent?.trim().substring(0, 100) : null,
                    price: priceText,
                    card_rect: {
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height,
                        visible: rect.y >= 0 && rect.y < window.innerHeight
                    },
                    image_rect: imgRect ? {
                        x: imgRect.x,
                        y: imgRect.y,
                        width: imgRect.width,
                        height: imgRect.height,
                        center_x: imgRect.x + imgRect.width / 2,
                        center_y: imgRect.y + imgRect.height / 2
                    } : null,
                    title_link: titleLinkEl ? {
                        href: titleLinkEl.href,
                        rect: (() => {
                            const r = titleLinkEl.getBoundingClientRect();
                            return {
                                x: r.x,
                                y: r.y,
                                width: r.width,
                                height: r.height,
                                center_x: r.x + r.width / 2,
                                center_y: r.y + r.height / 2
                            };
                        })()
                    } : null,
                    all_links_count: links.length
                });
            });

            return {
                viewport: {
                    width: window.innerWidth,
                    height: window.innerHeight
                },
                scroll_y: window.scrollY,
                products: results
            };
        }
        """)

        # 結果を保存
        with open(output_dir / f"products_{timestamp}.json", "w", encoding="utf-8") as f:
            json.dump(products_info, f, ensure_ascii=False, indent=2)

        print(f"   - 検出商品数: {len(products_info['products'])}")

        # 可視範囲の商品を表示
        visible_products = [p for p in products_info['products'] if p['card_rect']['visible']]
        print(f"   - 可視範囲の商品: {len(visible_products)}")

        for p in visible_products[:5]:
            print(f"     [{p['index']}] {p['title'][:40] if p['title'] else 'N/A'}...")
            print(f"         ASIN: {p['asin']}, 価格: {p['price']}")
            if p['image_rect']:
                print(f"         画像クリック位置: ({p['image_rect']['center_x']:.0f}, {p['image_rect']['center_y']:.0f})")

        # スクロールして調査
        print("\n5. スクロールして追加調査...")
        for scroll_num in range(1, 3):
            await page.evaluate("window.scrollBy(0, 600)")
            await page.wait_for_timeout(1500)

            await page.screenshot(
                path=str(output_dir / f"search_result_{timestamp}_scroll{scroll_num}.png"),
                full_page=False
            )

            # スクロール後の商品位置を再取得
            scroll_info = await page.evaluate("""
            () => {
                const items = document.querySelectorAll('[data-component-type="s-search-result"]');
                const visible = [];

                items.forEach((item, index) => {
                    const rect = item.getBoundingClientRect();
                    if (rect.y >= 0 && rect.y < window.innerHeight) {
                        const asin = item.getAttribute('data-asin');
                        const imgEl = item.querySelector('.s-image');
                        const imgRect = imgEl ? imgEl.getBoundingClientRect() : null;

                        visible.push({
                            index: index,
                            asin: asin,
                            card_y: rect.y,
                            image_center: imgRect ? {
                                x: imgRect.x + imgRect.width / 2,
                                y: imgRect.y + imgRect.height / 2
                            } : null
                        });
                    }
                });

                return {
                    scroll_y: window.scrollY,
                    visible_count: visible.length,
                    visible_products: visible
                };
            }
            """)

            print(f"   スクロール{scroll_num}: 可視商品 {scroll_info['visible_count']}件")

        # HTML構造のサンプルを保存
        print("\n6. HTML構造のサンプルを保存...")
        first_product_html = await page.evaluate("""
        () => {
            const item = document.querySelector('[data-component-type="s-search-result"]');
            return item ? item.outerHTML : null;
        }
        """)

        if first_product_html:
            with open(output_dir / f"product_html_sample_{timestamp}.html", "w", encoding="utf-8") as f:
                f.write(first_product_html)

        print(f"\n調査完了！結果は {output_dir} に保存されました")
        print("\n=== 重要な発見 ===")
        print("視覚ベースアプローチに必要な情報:")
        print("1. スクリーンショットを撮影")
        print("2. 商品画像の中心座標をクリック位置として使用")
        print("3. スクロールしながら目的の商品を探す")

        # ブラウザを少し開いたままにして確認できるようにする
        print("\n10秒後にブラウザを閉じます...")
        await page.wait_for_timeout(10000)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(investigate_amazon_search())
