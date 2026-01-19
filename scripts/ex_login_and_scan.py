"""
EX ログイン＆セレクタ調査

OTPが必要な場合は一時停止して待機
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
from dotenv import load_dotenv

load_dotenv()

MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")


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
                sel_id = await sel.get_attribute("id") or ""
                options = await sel.locator('option').all()
                option_samples = []
                for opt in options[:5]:
                    opt_text = (await opt.text_content() or "").strip()
                    opt_value = await opt.get_attribute("value") or ""
                    if opt_text:
                        option_samples.append({"text": opt_text, "value": opt_value})

                info["elements"]["selects"].append({
                    "id": sel_id,
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
                    href = await link.get_attribute("href") or ""
                    if text:
                        visible_links.append({"text": text[:50], "href": href})
            except:
                continue
        print(f"  links: {len(visible_links)}個")
        info["elements"]["links"] = visible_links[:30]
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
    print("EX ログイン & セレクタ調査")
    print("=" * 60)
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # ログイン
            print("ログインページにアクセス...")
            await page.goto("https://shinkansen2.jr-central.co.jp/RSV_P/smart_index.htm",
                          wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            print(f"会員ID入力: {MEMBER_ID}")
            await page.locator('role=textbox[name="会員ID"]').fill(MEMBER_ID)
            await page.wait_for_timeout(500)

            print("パスワード入力")
            await page.locator('role=textbox[name="パスワード"]').fill(PASSWORD)
            await page.wait_for_timeout(500)

            print("ログインボタンクリック")
            await page.locator('role=button[name="ログイン"]').click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(5000)

            # OTPが必要かチェック
            if await page.locator('input[value="自動音声案内発信"]').count() > 0:
                print("\n" + "=" * 60)
                print("OTP認証が必要です")
                print("=" * 60)
                print()

                print("自動音声案内発信ボタンをクリックします...")
                await page.locator('input[value="自動音声案内発信"]').click()
                await page.wait_for_timeout(3000)

                # ダイアログを閉じる
                print("ダイアログを閉じます...")
                close_buttons = await page.locator('button, input').all()
                for btn in close_buttons:
                    try:
                        text = await btn.text_content() or ''
                        value = await btn.get_attribute('value') or ''
                        if '閉じる' in text + value:
                            await btn.click(force=True)
                            await page.wait_for_timeout(2000)
                            break
                    except:
                        continue

                # OTP入力待機（ファイルから読み取り）
                print("\n" + "=" * 60)
                print("OTP入力待機中...")
                print("=" * 60)
                print()
                print("電話でOTPを受け取ったら、別のターミナルで以下を実行してください：")
                print("  echo OTPコード > otp_input.txt")
                print("例: echo 872213 > otp_input.txt")
                print()
                print("ファイルを監視中... (最大5分)")

                otp_file = "otp_input.txt"
                # 既存のファイルを削除
                if os.path.exists(otp_file):
                    os.remove(otp_file)

                # 5分間ファイルを監視
                otp_received = None
                for i in range(150):  # 150回 x 2秒 = 5分
                    await page.wait_for_timeout(2000)

                    if os.path.exists(otp_file):
                        try:
                            with open(otp_file, 'r', encoding='utf-8') as f:
                                otp_received = f.read().strip()
                            if otp_received and len(otp_received) == 6:
                                print(f"\nOTPコード受信: {otp_received}")
                                os.remove(otp_file)
                                break
                        except:
                            pass

                    if i % 15 == 0:  # 30秒ごとに表示
                        print(f"待機中... ({i*2}秒経過)")

                if not otp_received:
                    print("\nタイムアウト: OTPが受信できませんでした")
                    return

                # OTP入力
                print("OTPを入力...")
                await page.locator('input[type="tel"]').fill(otp_received)
                await page.wait_for_timeout(1000)

                print("次へボタンをクリック...")
                await page.locator('input[value="次へ"]').click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(5000)

            # ログイン後の確認
            current_url = page.url
            print(f"\n現在のURL: {current_url}")

            if "ClientService" in current_url or await page.locator('text="ログアウト"').count() > 0:
                print("OK ログイン成功\n")
            else:
                print("ログイン状態が不明です")
                await page.screenshot(path="ex_login_status.png")
                print("スクリーンショット: ex_login_status.png")
                return

            # マイページへ移動
            if "ClientService" not in current_url:
                print("マイページに移動...")
                await page.goto("https://shinkansen2.jr-central.co.jp/RSV_P/ClientService",
                              wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

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
                        price_locators = await page.locator('text=/￥\\d+,?\\d+/').all()
                        if len(price_locators) > 0:
                            await price_locators[0].click()
                            await page.wait_for_timeout(3000)

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
