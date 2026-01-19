"""
SmartEX セレクタ調査スクリプト

ログイン後の全ページを探索してセレクタ情報を収集
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

    # URLを取得
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

    # 全要素を取得してセレクタ候補を抽出
    selectors_info = {
        "page_name": page_name,
        "url": url,
        "timestamp": datetime.now().isoformat(),
        "buttons": [],
        "links": [],
        "inputs": [],
        "selects": [],
        "headings": [],
        "forms": [],
    }

    print("\n要素を調査中...")

    # ボタンを調査
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
            btn_type = await btn.evaluate("el => el.tagName.toLowerCase()")

            selectors_info["buttons"].append({
                "type": btn_type,
                "text": text,
                "value": value,
                "class": class_name,
            })
        except Exception:
            continue

    # リンクを調査
    links = await page.locator('a').all()
    print(f"リンク数: {len(links)}")
    for link in links:
        try:
            is_visible = await link.is_visible()
            if not is_visible:
                continue

            text = (await link.text_content() or "").strip()
            href = await link.get_attribute("href") or ""

            if text:  # テキストがあるものだけ
                selectors_info["links"].append({
                    "text": text,
                    "href": href,
                })
        except Exception:
            continue

    # 入力フィールドを調査
    inputs = await page.locator('input[type="text"], input[type="tel"], input[type="password"], textarea').all()
    print(f"入力フィールド数: {len(inputs)}")
    for inp in inputs:
        try:
            is_visible = await inp.is_visible()
            if not is_visible:
                continue

            input_type = await inp.get_attribute("type") or "text"
            name = await inp.get_attribute("name") or ""
            placeholder = await inp.get_attribute("placeholder") or ""
            aria_label = await inp.get_attribute("aria-label") or ""

            selectors_info["inputs"].append({
                "type": input_type,
                "name": name,
                "placeholder": placeholder,
                "aria_label": aria_label,
            })
        except Exception:
            continue

    # セレクトボックスを調査
    selects = await page.locator('select').all()
    print(f"セレクトボックス数: {len(selects)}")
    for select in selects:
        try:
            is_visible = await select.is_visible()
            if not is_visible:
                continue

            name = await select.get_attribute("name") or ""
            aria_label = await select.get_attribute("aria-label") or ""

            # オプションを取得
            options = await select.locator('option').all()
            option_texts = []
            for opt in options[:5]:  # 最初の5つだけ
                opt_text = (await opt.text_content() or "").strip()
                if opt_text:
                    option_texts.append(opt_text)

            selectors_info["selects"].append({
                "name": name,
                "aria_label": aria_label,
                "sample_options": option_texts,
            })
        except Exception:
            continue

    # 見出しを調査
    headings = await page.locator('h1, h2, h3, h4').all()
    print(f"見出し数: {len(headings)}")
    for heading in headings:
        try:
            is_visible = await heading.is_visible()
            if not is_visible:
                continue

            text = (await heading.text_content() or "").strip()
            tag = await heading.evaluate("el => el.tagName.toLowerCase()")

            if text:
                selectors_info["headings"].append({
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

    print(f"\n{page_name} の調査完了")


async def main():
    print("=" * 60)
    print("SmartEX セレクタ調査")
    print("=" * 60)
    print()

    if not MEMBER_ID or not PASSWORD:
        print("エラー: .envファイルに EX_MEMBER_ID と EX_PASSWORD を設定してください")
        return

    # 出力ディレクトリ作成
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = f"ex_investigation_{timestamp}"
    os.makedirs(output_dir, exist_ok=True)
    print(f"調査結果の保存先: {output_dir}\n")

    # セッションマネージャーを初期化
    session_mgr = SessionManager("smartex")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=300)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # Step 1: ログイン
            print("=" * 60)
            print("ログイン中...")
            print("=" * 60)

            # マイページにアクセス
            await page.goto("https://shinkansen2.jr-central.co.jp/RSV_P/p7A/ClientService",
                          wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            is_logged_in = await check_logged_in(page)

            if not is_logged_in:
                print("ログインします...")
                login_result = await login(page, MEMBER_ID, PASSWORD)

                if login_result.requires_otp:
                    print("\nOTP認証が必要です")
                    login_result = await complete_otp_authentication(
                        page=page,
                        otp_callback=get_otp_from_user,
                    )

                if not login_result.success:
                    print(f"ログイン失敗: {login_result.message}")
                    return

                await session_mgr.save_session(context)
                print("ログイン成功\n")
            else:
                print("既にログイン済み\n")

            # Step 2: マイページ調査
            await save_page_info(page, "01_mypage", output_dir)
            await page.wait_for_timeout(2000)

            # Step 3: 列車検索ページを開く
            print("\n" + "=" * 60)
            print("列車検索ページを開きます...")
            print("=" * 60)

            # 「列車を検索」ボタンをクリック
            search_button = page.locator('article:has-text("列車を検索")')
            if await search_button.count() > 0:
                await search_button.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(3000)

                await save_page_info(page, "02_search_form", output_dir)

                # Step 4: 検索フォームに入力して検索実行
                print("\n" + "=" * 60)
                print("検索条件を入力します...")
                print("=" * 60)

                # サンプル検索: 東京→名古屋
                # selectタグのみを取得（正確に）
                selects = await page.locator('select').all()
                print(f"select数: {len(selects)}")

                # 出発駅（4番目のselect、インデックス4）
                if len(selects) > 4:
                    # 利用可能なオプションを確認
                    options = await selects[4].locator('option').all()
                    print(f"出発駅オプション数: {len(options)}")
                    if len(options) > 0:
                        first_option = await options[0].text_content()
                        print(f"最初のオプション: {first_option}")

                    # 「東　京」を選択（全角スペースあり）
                    await selects[4].select_option(label="東　京")
                    print("出発駅: 東　京")

                # 到着駅（5番目のselect、インデックス5）
                if len(selects) > 5:
                    await selects[5].select_option(label="名古屋")
                    print("到着駅: 名古屋")

                await page.wait_for_timeout(2000)

                # 「予約を続ける」ボタンをクリック
                continue_btn = page.locator('input[type="submit"][value*="予約"]')
                if await continue_btn.count() > 0:
                    await continue_btn.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await page.wait_for_timeout(3000)

                    await save_page_info(page, "03_search_results", output_dir)

                    # Step 5: 列車候補を選択
                    print("\n" + "=" * 60)
                    print("列車候補を選択します...")
                    print("=" * 60)

                    # 「この候補を選択」ボタンをクリック（最初の候補）
                    select_btn = page.locator('text="この候補を選択"').first
                    if await select_btn.count() > 0:
                        await select_btn.click()
                        await page.wait_for_load_state("domcontentloaded")
                        await page.wait_for_timeout(3000)

                        await save_page_info(page, "04_product_selection", output_dir)

                        # Step 6: 商品を選択（普通車指定席）
                        print("\n" + "=" * 60)
                        print("商品を選択します...")
                        print("=" * 60)

                        # 価格表示（スマートEX）をクリック
                        price_elements = await page.locator('text=/￥\\d+,?\\d+/').all()
                        print(f"価格表示数: {len(price_elements)}")

                        if len(price_elements) > 0:
                            # 最初の価格（普通車指定席）をクリック
                            await price_elements[0].click()
                            await page.wait_for_timeout(3000)

                            # 「予約を続ける」ボタンをクリック
                            continue_btn2 = page.locator('input[type="submit"][value*="予約"]')
                            if await continue_btn2.count() > 0:
                                await continue_btn2.click()
                                await page.wait_for_load_state("domcontentloaded")
                                await page.wait_for_timeout(3000)

                                await save_page_info(page, "05_confirmation", output_dir)

            # 最終結果サマリー作成
            summary = {
                "investigation_date": datetime.now().isoformat(),
                "member_id": MEMBER_ID,
                "pages_investigated": [
                    "01_mypage - マイページ（ログイン後のトップ）",
                    "02_search_form - 列車検索フォーム",
                    "03_search_results - 検索結果（列車候補一覧）",
                    "04_product_selection - 商品選択（座席タイプ選択）",
                    "05_confirmation - 最終確認画面",
                ],
                "output_directory": output_dir,
            }

            summary_path = f"{output_dir}/00_summary.json"
            with open(summary_path, 'w', encoding='utf-8') as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)

            print("\n" + "=" * 60)
            print("調査完了")
            print("=" * 60)
            print(f"\n全ての調査結果は {output_dir} に保存されました")
            print("\nブラウザを30秒間保持します（確認用）")
            await page.wait_for_timeout(30000)

        except Exception as e:
            print(f"\nエラー: {e}")
            import traceback
            traceback.print_exc()

            # エラー時もスクリーンショット
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
