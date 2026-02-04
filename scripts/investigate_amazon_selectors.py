"""
Amazon セレクタ調査スクリプト

現在のAmazon.co.jpのHTML構造を調査し、正確なセレクタを特定する。
"""

import asyncio
from playwright.async_api import async_playwright
from datetime import datetime


async def investigate_amazon():
    """Amazon の各画面でセレクタを調査"""

    async with async_playwright() as p:
        # ブラウザを起動（ユーザーデータを使用してログイン状態を維持）
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print("=" * 60)
        print("Amazon セレクタ調査開始")
        print("=" * 60)

        # ========================================
        # 1. トップページ - 検索ボックス
        # ========================================
        print("\n[1] トップページ - 検索ボックス調査")
        await page.goto("https://www.amazon.co.jp/")
        await page.wait_for_timeout(3000)

        # 検索ボックス候補を調査
        search_candidates = [
            "#twotabsearchtextbox",
            "#nav-search-bar-form input[type='text']",
            "input[name='field-keywords']",
            "[data-action='nav-input']",
        ]

        print("\n検索ボックス候補:")
        for selector in search_candidates:
            try:
                elem = page.locator(selector)
                count = await elem.count()
                if count > 0:
                    visible = await elem.first.is_visible()
                    print(f"  ✅ {selector} - count={count}, visible={visible}")
                else:
                    print(f"  ❌ {selector} - not found")
            except Exception as e:
                print(f"  ❌ {selector} - error: {e}")

        # 検索ボタン候補
        search_btn_candidates = [
            "#nav-search-submit-button",
            "input[type='submit'][value='検索']",
            "#nav-search-bar-form button",
        ]

        print("\n検索ボタン候補:")
        for selector in search_btn_candidates:
            try:
                elem = page.locator(selector)
                count = await elem.count()
                if count > 0:
                    visible = await elem.first.is_visible()
                    print(f"  ✅ {selector} - count={count}, visible={visible}")
                else:
                    print(f"  ❌ {selector} - not found")
            except Exception as e:
                print(f"  ❌ {selector} - error: {e}")

        # ========================================
        # 2. 検索実行 → 検索結果ページ
        # ========================================
        print("\n[2] 検索結果ページ調査")
        search_box = page.locator("#twotabsearchtextbox")
        await search_box.fill("アベンヌウォーター")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(3000)

        # HTMLを保存
        html = await page.content()
        with open("amazon_search_results.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("  → amazon_search_results.html に保存")

        # 検索結果アイテム候補
        result_candidates = [
            '[data-component-type="s-search-result"]',
            '[data-asin]:not([data-asin=""])',
            '.s-result-item[data-asin]',
            '.s-main-slot .s-result-item',
        ]

        print("\n検索結果アイテム候補:")
        for selector in result_candidates:
            try:
                elem = page.locator(selector)
                count = await elem.count()
                print(f"  {'✅' if count > 0 else '❌'} {selector} - count={count}")
            except Exception as e:
                print(f"  ❌ {selector} - error: {e}")

        # 商品タイトルセレクタ
        title_candidates = [
            'h2 a span',
            'h2.a-size-mini span',
            '[data-component-type="s-search-result"] h2',
            '.s-title-instructions-style a span',
        ]

        print("\n商品タイトル候補:")
        for selector in title_candidates:
            try:
                elem = page.locator(selector)
                count = await elem.count()
                if count > 0:
                    first_text = await elem.first.text_content()
                    print(f"  ✅ {selector} - count={count}")
                    print(f"      例: {first_text[:50]}...")
                else:
                    print(f"  ❌ {selector} - not found")
            except Exception as e:
                print(f"  ❌ {selector} - error: {e}")

        # 価格セレクタ
        price_candidates = [
            '.a-price .a-offscreen',
            '.a-price-whole',
            '[data-a-color="base"] .a-offscreen',
        ]

        print("\n価格候補:")
        for selector in price_candidates:
            try:
                elem = page.locator(selector)
                count = await elem.count()
                if count > 0:
                    first_text = await elem.first.text_content()
                    print(f"  ✅ {selector} - count={count}, 例: {first_text}")
                else:
                    print(f"  ❌ {selector} - not found")
            except Exception as e:
                print(f"  ❌ {selector} - error: {e}")

        # ========================================
        # 3. 商品詳細ページ
        # ========================================
        print("\n[3] 商品詳細ページ調査")

        # 最初の商品をクリック
        first_product = page.locator('[data-component-type="s-search-result"]').first
        product_link = first_product.locator('h2 a')
        await product_link.click()
        await page.wait_for_timeout(3000)

        # HTMLを保存
        html = await page.content()
        with open("amazon_product_detail.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("  → amazon_product_detail.html に保存")

        # 商品タイトル
        detail_title_candidates = [
            '#productTitle',
            '#title',
            'h1#title span',
        ]

        print("\n商品詳細 - タイトル候補:")
        for selector in detail_title_candidates:
            try:
                elem = page.locator(selector)
                count = await elem.count()
                if count > 0:
                    text = await elem.first.text_content()
                    print(f"  ✅ {selector} - {text[:50].strip()}...")
                else:
                    print(f"  ❌ {selector} - not found")
            except Exception as e:
                print(f"  ❌ {selector} - error: {e}")

        # カートに入れるボタン
        cart_btn_candidates = [
            '#add-to-cart-button',
            'input[name="submit.add-to-cart"]',
            '#add-to-cart-button-ubb',
            '[data-action="add-to-cart-form"]',
        ]

        print("\nカートに入れるボタン候補:")
        for selector in cart_btn_candidates:
            try:
                elem = page.locator(selector)
                count = await elem.count()
                if count > 0:
                    visible = await elem.first.is_visible()
                    print(f"  ✅ {selector} - count={count}, visible={visible}")
                else:
                    print(f"  ❌ {selector} - not found")
            except Exception as e:
                print(f"  ❌ {selector} - error: {e}")

        # 今すぐ買うボタン
        buy_now_candidates = [
            '#buy-now-button',
            'input[name="submit.buy-now"]',
        ]

        print("\n今すぐ買うボタン候補:")
        for selector in buy_now_candidates:
            try:
                elem = page.locator(selector)
                count = await elem.count()
                if count > 0:
                    visible = await elem.first.is_visible()
                    print(f"  ✅ {selector} - count={count}, visible={visible}")
                else:
                    print(f"  ❌ {selector} - not found")
            except Exception as e:
                print(f"  ❌ {selector} - error: {e}")

        # 数量選択
        qty_candidates = [
            '#quantity',
            'select[name="quantity"]',
            '#a-autoid-0-announce',
        ]

        print("\n数量選択候補:")
        for selector in qty_candidates:
            try:
                elem = page.locator(selector)
                count = await elem.count()
                if count > 0:
                    print(f"  ✅ {selector} - count={count}")
                else:
                    print(f"  ❌ {selector} - not found")
            except Exception as e:
                print(f"  ❌ {selector} - error: {e}")

        # ========================================
        # 4. カートに追加 → カート確認
        # ========================================
        print("\n[4] カート追加後の確認画面調査")

        add_btn = page.locator('#add-to-cart-button')
        if await add_btn.count() > 0:
            await add_btn.click()
            await page.wait_for_timeout(3000)

            # HTMLを保存
            html = await page.content()
            with open("amazon_cart_added.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("  → amazon_cart_added.html に保存")

            # カート追加成功メッセージ
            success_candidates = [
                '#NATC_SMART_WAGON_CONF_MSG_SUCCESS',
                'text="カートに入れました"',
                '.a-alert-success',
                '#sw-atc-confirmation',
            ]

            print("\nカート追加成功メッセージ候補:")
            for selector in success_candidates:
                try:
                    elem = page.locator(selector)
                    count = await elem.count()
                    if count > 0:
                        print(f"  ✅ {selector} - count={count}")
                    else:
                        print(f"  ❌ {selector} - not found")
                except Exception as e:
                    print(f"  ❌ {selector} - error: {e}")

            # レジに進むボタン
            checkout_btn_candidates = [
                '[name="proceedToRetailCheckout"]',
                '#sc-buy-box-ptc-button',
                'input[data-feature-id="proceed-to-checkout-action"]',
                'text="レジに進む"',
            ]

            print("\nレジに進むボタン候補:")
            for selector in checkout_btn_candidates:
                try:
                    elem = page.locator(selector)
                    count = await elem.count()
                    if count > 0:
                        visible = await elem.first.is_visible()
                        print(f"  ✅ {selector} - count={count}, visible={visible}")
                    else:
                        print(f"  ❌ {selector} - not found")
                except Exception as e:
                    print(f"  ❌ {selector} - error: {e}")

        # ========================================
        # 5. チェックアウト画面（既に開いているタブを利用）
        # ========================================
        print("\n[5] チェックアウト画面調査")
        print("  → 既存のチェックアウトタブから情報を取得")

        # 既存タブを探す
        for p in context.pages:
            if "checkout" in p.url or "レジ" in await p.title():
                print(f"  → チェックアウトタブ発見: {p.url}")

                # HTMLを保存
                html = await p.content()
                with open("amazon_checkout.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("  → amazon_checkout.html に保存")

                # 注文確定ボタン
                order_btn_candidates = [
                    'input[name="placeYourOrder1"]',
                    '#submitOrderButtonId',
                    'text="注文を確定する"',
                    '.place-your-order-button',
                ]

                print("\n注文確定ボタン候補:")
                for selector in order_btn_candidates:
                    try:
                        elem = p.locator(selector)
                        count = await elem.count()
                        if count > 0:
                            print(f"  ✅ {selector} - count={count}")
                        else:
                            print(f"  ❌ {selector} - not found")
                    except Exception as e:
                        print(f"  ❌ {selector} - error: {e}")

                break

        print("\n" + "=" * 60)
        print("調査完了")
        print("=" * 60)
        print("\n保存されたHTMLファイル:")
        print("  - amazon_search_results.html")
        print("  - amazon_product_detail.html")
        print("  - amazon_cart_added.html")
        print("  - amazon_checkout.html")

        await page.close()


if __name__ == "__main__":
    asyncio.run(investigate_amazon())
