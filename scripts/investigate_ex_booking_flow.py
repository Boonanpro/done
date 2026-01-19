"""
SmartEX 予約フロー調査スクリプト

検索結果→商品選択→確認画面のセレクタを調査
"""
import asyncio
import os
import sys
import json
from pathlib import Path
from datetime import datetime

# プロジェクトルートをPATHに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from dotenv import load_dotenv

from app.executors.ex_reservation.login import login, complete_otp_authentication, check_logged_in
from app.utils.session_manager import SessionManager

# .envファイルを読み込み
load_dotenv()

# 認証情報を環境変数から取得
MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")


async def get_otp_from_user() -> str:
    """ユーザーからOTPを取得するコールバック関数"""
    print("\n" + "=" * 60)
    print("電話にOTPが届いているはずです")
    print("=" * 60)

    loop = asyncio.get_event_loop()
    otp_code = await loop.run_in_executor(
        None,
        lambda: input("\nOTPコード（6桁）を入力してください: ").strip()
    )

    return otp_code


async def save_page_info(page, page_name: str, output_dir: str):
    """ページの情報を保存"""
    print(f"\n{'=' * 60}")
    print(f"ページ調査: {page_name}")
    print(f"{'=' * 60}")

    url = page.url
    print(f"URL: {url}")

    # スクリーンショット保存
    screenshot_path = f"{output_dir}/{page_name}_screenshot.png"
    await page.screenshot(path=screenshot_path, full_page=True)
    print(f"スクリーンショット: {screenshot_path}")

    # HTML保存
    html_path = f"{output_dir}/{page_name}_page.html"
    content = await page.content()
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"HTML保存: {html_path}")

    # セレクタ情報を収集
    selectors_info = {
        "page_name": page_name,
        "url": url,
        "timestamp": datetime.now().isoformat(),
        "buttons": [],
        "links": [],
        "text_content": [],
        "prices": [],
        "train_info": [],
    }

    print("\n要素を調査中...")

    # ボタン
    buttons = await page.locator('button, input[type="submit"], input[type="button"]').all()
    print(f"ボタン数: {len(buttons)}")
    for btn in buttons:
        try:
            is_visible = await btn.is_visible()
            if not is_visible:
                continue

            text = (await btn.text_content() or "").strip()
            value = await btn.get_attribute("value") or ""
            class_name = await btn.get_attribute("class") or ""

            selectors_info["buttons"].append({
                "text": text,
                "value": value,
                "class": class_name,
            })
        except Exception:
            continue

    # 価格表示（￥を含むテキスト）
    price_elements = await page.locator('text=/￥\\d+,?\\d+/').all()
    print(f"価格表示数: {len(price_elements)}")
    for price_elem in price_elements:
        try:
            is_visible = await price_elem.is_visible()
            if not is_visible:
                continue

            text = (await price_elem.text_content() or "").strip()
            selectors_info["prices"].append(text)
        except Exception:
            continue

    # 見出し
    headings = await page.locator('h1, h2, h3, h4').all()
    for heading in headings:
        try:
            is_visible = await heading.is_visible()
            if not is_visible:
                continue

            text = (await heading.text_content() or "").strip()
            tag = await heading.evaluate("el => el.tagName.toLowerCase()")

            if text:
                selectors_info["text_content"].append({
                    "tag": tag,
                    "text": text,
                })
        except Exception:
            continue

    # JSON保存
    json_path = f"{output_dir}/{page_name}_selectors.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(selectors_info, f, ensure_ascii=False, indent=2)
    print(f"セレクタ情報保存: {json_path}")


async def main():
    print("=" * 60)
    print("SmartEX 予約フロー調査")
    print("=" * 60)
    print()

    if not MEMBER_ID or not PASSWORD:
        print("エラー: .envファイルに EX_MEMBER_ID と EX_PASSWORD を設定してください")
        return

    # 出力ディレクトリ作成
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = f"ex_booking_flow_{timestamp}"
    os.makedirs(output_dir, exist_ok=True)
    print(f"調査結果の保存先: {output_dir}\n")

    # セッションマネージャーを初期化
    session_mgr = SessionManager("smartex")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # ログイン
            print("=" * 60)
            print("ログイン中...")
            print("=" * 60)

            await page.goto("https://shinkansen2.jr-central.co.jp/RSV_P/p7A/ClientService",
                          wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            is_logged_in = await check_logged_in(page)

            if not is_logged_in:
                print("ログインします...")
                login_result = await login(page, MEMBER_ID, PASSWORD)

                if login_result.requires_otp:
                    login_result = await complete_otp_authentication(
                        page=page,
                        otp_callback=get_otp_from_user,
                    )

                if not login_result.success:
                    print(f"ログイン失敗: {login_result.message}")
                    return

                await session_mgr.save_session(context)

            print("ログイン済み\n")

            # 検索フォームを開く
            print("=" * 60)
            print("検索フォームを開きます...")
            print("=" * 60)

            search_button = page.locator('article:has-text("列車を検索")')
            if await search_button.count() > 0:
                await search_button.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(3000)

                print("検索フォーム表示完了\n")

                # 検索条件を入力（新大阪→博多、19時台）
                print("=" * 60)
                print("検索条件を入力: 新大阪 → 博多 19時台")
                print("=" * 60)

                selects = await page.locator('select').all()

                # 時刻（1番目のselect: 時）
                if len(selects) > 1:
                    await selects[1].select_option(label="19時")
                    print("時刻: 19時")

                # 出発駅（4番目のselect）
                if len(selects) > 4:
                    await selects[4].select_option(label="新大阪")
                    print("出発駅: 新大阪")

                # 到着駅（5番目のselect）
                if len(selects) > 5:
                    await selects[5].select_option(label="博　多")
                    print("到着駅: 博多")

                # 大人人数（7番目のselect）
                if len(selects) > 7:
                    await selects[7].select_option(label="おとな1名")
                    print("人数: おとな1名")

                await page.wait_for_timeout(2000)

                # 検索実行
                print("\n検索を実行します...")
                continue_btn = page.locator('input[type="submit"][value*="予約"]')
                if await continue_btn.count() > 0:
                    await continue_btn.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await page.wait_for_timeout(3000)

                    await save_page_info(page, "01_search_results", output_dir)

                    # 列車候補を選択
                    print("\n=" * 60)
                    print("列車候補を選択します...")
                    print("=" * 60)

                    # 「この候補を選択」ボタンを探す
                    select_buttons = await page.locator('text="この候補を選択"').all()
                    print(f"候補数: {len(select_buttons)}")

                    if len(select_buttons) > 0:
                        # 最初の候補を選択
                        await select_buttons[0].click()
                        await page.wait_for_load_state("domcontentloaded")
                        await page.wait_for_timeout(3000)

                        await save_page_info(page, "02_product_selection", output_dir)

                        # 商品を選択（普通車指定席）
                        print("\n=" * 60)
                        print("商品（普通車指定席）を選択します...")
                        print("=" * 60)

                        # 価格表示を全て取得
                        price_locators = await page.locator('text=/￥\\d+,?\\d+/').all()
                        print(f"価格表示数: {len(price_locators)}")

                        # 最初の価格をクリック（普通車指定席）
                        if len(price_locators) > 0:
                            # 価格の中で○マークが付いているものを探す
                            clickable_prices = []
                            for price_loc in price_locators:
                                try:
                                    # 親要素に○があるかチェック
                                    parent = price_loc.locator('..')
                                    parent_text = await parent.text_content()
                                    if '○' in parent_text:
                                        clickable_prices.append(price_loc)
                                except:
                                    continue

                            if clickable_prices:
                                print(f"クリック可能な価格: {len(clickable_prices)}件")
                                await clickable_prices[0].click()
                                await page.wait_for_timeout(3000)
                            else:
                                # ○マークがない場合は最初の価格をクリック
                                print("○マーク付き価格が見つからないため、最初の価格をクリック")
                                await price_locators[0].click()
                                await page.wait_for_timeout(3000)

                            # 「予約を続ける」ボタンをクリック
                            continue_btn2 = page.locator('input[type="submit"][value*="予約"], button:has-text("予約を続ける")')
                            if await continue_btn2.count() > 0:
                                print("「予約を続ける」ボタンをクリック")
                                await continue_btn2.first.click()
                                await page.wait_for_load_state("domcontentloaded")
                                await page.wait_for_timeout(3000)

                                await save_page_info(page, "03_confirmation", output_dir)

                                print("\n=" * 60)
                                print("調査完了！")
                                print("=" * 60)
                                print(f"\n確認画面まで到達しました")
                                print("※購入は実行していません")
                        else:
                            print("価格表示が見つかりませんでした")
                    else:
                        print("列車候補が見つかりませんでした")

            # サマリー作成
            summary = {
                "investigation_date": datetime.now().isoformat(),
                "search_condition": "新大阪 → 博多 19時台",
                "pages_investigated": [
                    "01_search_results - 検索結果（列車候補一覧）",
                    "02_product_selection - 商品選択（座席タイプ選択）",
                    "03_confirmation - 最終確認画面",
                ],
                "output_directory": output_dir,
            }

            summary_path = f"{output_dir}/00_summary.json"
            with open(summary_path, 'w', encoding='utf-8') as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)

            print(f"\n全ての調査結果は {output_dir} に保存されました")
            print("\nブラウザを30秒間保持します（確認用）")
            await page.wait_for_timeout(30000)

        except Exception as e:
            print(f"\nエラー: {e}")
            import traceback
            traceback.print_exc()

            try:
                screenshot_path = f"{output_dir}/error_screenshot.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"エラー画面保存: {screenshot_path}")
            except Exception:
                pass

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
