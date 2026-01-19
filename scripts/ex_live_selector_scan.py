"""
EX セレクタ完全調査

保存済みセッションを使用して全ページを調査
"""
import asyncio
import os
import sys
import json
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from app.utils.session_manager import SessionManager


async def scan_page(page, page_name: str):
    """ページを詳細にスキャン"""
    print(f"\n{'=' * 60}")
    print(f"スキャン中: {page_name}")
    print(f"{'=' * 60}")

    url = page.url
    print(f"URL: {url}")

    # スクリーンショット
    screenshot_path = f"ex_scan_{page_name}.png"
    await page.screenshot(path=screenshot_path, full_page=True)
    print(f"スクリーンショット: {screenshot_path}")

    info = {
        "page_name": page_name,
        "url": url,
        "timestamp": datetime.now().isoformat(),
        "elements": {}
    }

    # 全てのボタン・入力・リンク・セレクトを調査
    print("\n要素をスキャン中...")

    # role属性付き要素
    roles = ["button", "textbox", "combobox", "link", "heading"]
    for role in roles:
        try:
            elements = await page.locator(f'[role="{role}"]').all()
            print(f"  role={role}: {len(elements)}個")
            info["elements"][f"role_{role}"] = []
            for elem in elements:
                try:
                    if not await elem.is_visible():
                        continue
                    name_attr = await elem.get_attribute("name") or ""
                    aria_label = await elem.get_attribute("aria-label") or ""
                    text = (await elem.text_content() or "").strip()[:100]

                    info["elements"][f"role_{role}"].append({
                        "name": name_attr,
                        "aria_label": aria_label,
                        "text": text,
                    })
                except:
                    continue
        except:
            continue

    # input要素
    try:
        inputs = await page.locator('input').all()
        print(f"  input: {len(inputs)}個")
        info["elements"]["inputs"] = []
        for inp in inputs:
            try:
                if not await inp.is_visible():
                    continue
                inp_type = await inp.get_attribute("type") or ""
                value = await inp.get_attribute("value") or ""
                name = await inp.get_attribute("name") or ""

                info["elements"]["inputs"].append({
                    "type": inp_type,
                    "value": value,
                    "name": name,
                })
            except:
                continue
    except:
        pass

    # select要素
    try:
        selects = await page.locator('select').all()
        print(f"  select: {len(selects)}個")
        info["elements"]["selects"] = []
        for sel in selects:
            try:
                if not await sel.is_visible():
                    continue
                name = await sel.get_attribute("name") or ""
                options = await sel.locator('option').all()
                option_samples = []
                for opt in options[:3]:
                    opt_text = (await opt.text_content() or "").strip()
                    if opt_text:
                        option_samples.append(opt_text)

                info["elements"]["selects"].append({
                    "name": name,
                    "option_count": len(options),
                    "sample_options": option_samples,
                })
            except:
                continue
    except:
        pass

    # 見出し
    try:
        headings = await page.locator('h1, h2, h3, h4').all()
        print(f"  headings: {len(headings)}個")
        info["elements"]["headings"] = []
        for h in headings:
            try:
                if not await h.is_visible():
                    continue
                text = (await h.text_content() or "").strip()
                tag = await h.evaluate("el => el.tagName")
                if text:
                    info["elements"]["headings"].append({
                        "tag": tag,
                        "text": text[:100],
                    })
            except:
                continue
    except:
        pass

    # aタグ
    try:
        links = await page.locator('a').all()
        visible_links = []
        for link in links:
            try:
                if await link.is_visible():
                    text = (await link.text_content() or "").strip()
                    if text:
                        visible_links.append(text[:50])
            except:
                continue
        print(f"  links: {len(visible_links)}個")
        info["elements"]["links"] = visible_links[:20]
    except:
        pass

    # 価格表示
    try:
        prices = await page.locator('text=/￥\\d+/').all()
        price_texts = []
        for p in prices:
            try:
                if await p.is_visible():
                    text = (await p.text_content() or "").strip()
                    if text:
                        price_texts.append(text)
            except:
                continue
        if price_texts:
            print(f"  prices: {len(price_texts)}個")
            info["elements"]["prices"] = price_texts
    except:
        pass

    # JSON保存
    json_path = f"ex_scan_{page_name}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"データ保存: {json_path}")

    return info


async def main():
    print("=" * 60)
    print("EX セレクタ完全調査")
    print("=" * 60)
    print()

    # セッションマネージャー
    session_mgr = SessionManager("smartex")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # マイページにアクセス
            print("マイページにアクセス中...")
            await page.goto("https://shinkansen2.jr-central.co.jp/RSV_P/ClientService",
                          wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # ログアウトリンクがあるか確認
            logout = await page.locator('text="ログアウト"').count()
            if logout > 0:
                print("OK ログイン済み\n")
            else:
                print("NG ログインが必要です。先にログインしてください。")
                return

            # 1. マイページ調査
            await scan_page(page, "01_mypage")
            await page.wait_for_timeout(2000)

            # 2. 検索フォームを開く
            print("\n検索フォームを開きます...")
            search_btn = page.locator('article:has-text("列車を検索")')
            if await search_btn.count() > 0:
                await search_btn.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(3000)

                await scan_page(page, "02_search_form")

                # 3. 検索実行（新大阪→博多 19時）
                print("\n検索実行: 新大阪→博多 19時")
                selects = await page.locator('select').all()

                if len(selects) > 1:
                    await selects[1].select_option(label="19時")
                if len(selects) > 4:
                    await selects[4].select_option(label="新大阪")
                if len(selects) > 5:
                    await selects[5].select_option(label="博　多")
                if len(selects) > 7:
                    await selects[7].select_option(label="おとな1名")

                await page.wait_for_timeout(2000)

                continue_btn = page.locator('input[type="submit"][value*="予約"]')
                if await continue_btn.count() > 0:
                    await continue_btn.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await page.wait_for_timeout(3000)

                    await scan_page(page, "03_search_results")

                    # 4. 列車選択
                    print("\n最初の列車候補を選択...")
                    select_btns = await page.locator('text="この候補を選択"').all()
                    if len(select_btns) > 0:
                        await select_btns[0].click()
                        await page.wait_for_load_state("domcontentloaded")
                        await page.wait_for_timeout(3000)

                        await scan_page(page, "04_seat_selection")

                        # 5. 商品選択（普通車指定席）
                        print("\n商品を選択...")
                        # ○付きの価格を探す
                        price_locators = await page.locator('text=/￥\\d+,?\\d+/').all()
                        if len(price_locators) > 0:
                            # 最初の価格をクリック
                            await price_locators[0].click()
                            await page.wait_for_timeout(3000)

                            # 予約を続けるボタン
                            continue_btn2 = page.locator('input[type="submit"][value*="予約"]')
                            if await continue_btn2.count() > 0:
                                await continue_btn2.first.click()
                                await page.wait_for_load_state("domcontentloaded")
                                await page.wait_for_timeout(3000)

                                await scan_page(page, "05_confirmation")

                                print("\n" + "=" * 60)
                                print("全ページの調査完了！")
                                print("=" * 60)

            print("\nブラウザを30秒間保持します...")
            await page.wait_for_timeout(30000)

        except Exception as e:
            print(f"\nエラー: {e}")
            import traceback
            traceback.print_exc()

            try:
                await page.screenshot(path="ex_scan_error.png", full_page=True)
                print("エラー画面: ex_scan_error.png")
            except:
                pass

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
