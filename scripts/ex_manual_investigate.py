"""
EX セレクタ調査（手動実行用）

ターミナルで直接実行してください：
python scripts/ex_manual_investigate.py
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
from app.executors.ex_reservation.login import login, request_otp, close_otp_dialog, enter_otp

load_dotenv()

MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")


async def save_page_info(page, page_name: str):
    """ページ情報を保存"""
    print(f"\n{'=' * 60}")
    print(f"ページ: {page_name}")
    print(f"{'=' * 60}")

    url = page.url
    print(f"URL: {url}")

    # スクリーンショット
    screenshot = f"ex_{page_name}.png"
    await page.screenshot(path=screenshot, full_page=True)
    print(f"スクリーンショット: {screenshot}")

    # HTML
    html_file = f"ex_{page_name}.html"
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(await page.content())
    print(f"HTML: {html_file}")

    # 要素カウント
    print("\n要素数:")
    buttons = await page.locator('button, input[type="submit"], input[type="button"]').count()
    links = await page.locator('a').count()
    selects = await page.locator('select').count()
    inputs = await page.locator('input').count()

    print(f"  ボタン: {buttons}")
    print(f"  リンク: {links}")
    print(f"  セレクト: {selects}")
    print(f"  入力フィールド: {inputs}")

    # セレクトボックスの詳細
    if selects > 0:
        print("\nセレクトボックスの詳細:")
        select_elements = await page.locator('select').all()
        for i, sel in enumerate(select_elements[:10]):  # 最初の10個
            try:
                is_visible = await sel.is_visible()
                if not is_visible:
                    continue

                name = await sel.get_attribute('name') or ''
                sel_id = await sel.get_attribute('id') or ''

                # オプションのサンプル
                options = await sel.locator('option').all()
                sample_options = []
                for opt in options[:3]:
                    text = (await opt.text_content() or '').strip()
                    if text:
                        sample_options.append(text)

                print(f"  [{i}] id={sel_id} name={name} options={len(options)} sample={sample_options}")
            except:
                pass


async def main():
    print("=" * 60)
    print("EX セレクタ調査（対話モード）")
    print("=" * 60)
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # ステップ1: ログイン
            print("ステップ1: ログイン")
            result = await login(page, MEMBER_ID, PASSWORD)

            if result.requires_otp:
                print("\nOTP認証が必要です")

                # OTP発信
                print("自動音声案内を発信します...")
                otp_result = await request_otp(page)
                print(f"結果: {otp_result.message}")

                await page.wait_for_timeout(3000)

                # ダイアログを閉じる（失敗しても続行）
                print("ダイアログを閉じます...")
                close_result = await close_otp_dialog(page)
                if not close_result.success:
                    print(f"警告: {close_result.message}")
                    print("（ダイアログがない場合もあるので続行します）")

                # OTP入力
                otp_code = input("\n電話で受け取ったOTPコード（6桁）を入力: ").strip()

                print(f"OTP入力: {otp_code}")
                otp_login_result = await enter_otp(page, otp_code)

                if not otp_login_result.success:
                    print(f"OTP認証失敗: {otp_login_result.message}")
                    await page.screenshot(path="ex_otp_error.png")
                    return

            if not result.success and result.requires_otp:
                # OTP後の最終確認
                pass
            elif not result.success:
                print(f"ログイン失敗: {result.message}")
                return

            print("\nログイン成功！")

            # マイページ
            await save_page_info(page, "01_mypage")

            input("\nEnterキーを押すと検索フォームを開きます...")

            # 検索フォームを開く
            print("\nステップ2: 検索フォームを開く")
            search_btn = page.locator('article:has-text("列車を検索")')
            if await search_btn.count() > 0:
                await search_btn.click()
                await page.wait_for_timeout(3000)

                await save_page_info(page, "02_search_form")

                input("\nEnterキーを押すと検索を実行します（新大阪→博多 19時）...")

                # 検索実行
                print("\nステップ3: 検索実行")

                # ID指定で確実に選択（valueで指定）
                print("時刻: 19時")
                await page.locator('#s-3').select_option(value="19")

                print("乗車駅: 新大阪")
                await page.locator('#s6').select_option(value="170")

                print("降車駅: 博多")
                await page.locator('#s7').select_option(value="350")

                print("人数: おとな1名")
                await page.locator('#s10').select_option(value="01")

                await page.wait_for_timeout(2000)

                continue_btn = page.locator('input[type="submit"][value*="予約"]')
                if await continue_btn.count() > 0:
                    await continue_btn.click()
                    await page.wait_for_timeout(3000)

                    # 時間帯の注意事項ページかチェック
                    notice_heading = await page.locator('text="予約のご案内"').count()
                    if notice_heading > 0:
                        print("\n時間帯の注意事項ページが表示されました")
                        await save_page_info(page, "03a_time_notice")

                        # 「予約を続ける」ボタンをクリック
                        continue_btn2 = page.locator('button:has-text("予約を続ける")')
                        if await continue_btn2.count() > 0:
                            print("「予約を続ける」ボタンをクリック")
                            await continue_btn2.click()
                            await page.wait_for_timeout(3000)

                    await save_page_info(page, "03_search_results")

                    input("\nEnterキーを押すと最初の列車を選択します...")

                    # 列車選択
                    print("\nステップ4: 列車選択")
                    select_btns = await page.locator('text="この候補を選択"').all()
                    if len(select_btns) > 0:
                        await select_btns[0].click()
                        await page.wait_for_timeout(3000)

                        await save_page_info(page, "04_seat_selection")

                        input("\nEnterキーを押すと商品（普通車指定席）を選択します...")

                        # 商品選択
                        print("\nステップ5: 商品選択")
                        price_elements = await page.locator('text=/￥\\d+,?\\d+/').all()
                        if len(price_elements) > 0:
                            await price_elements[0].click()
                            await page.wait_for_timeout(3000)

                            continue_btn2 = page.locator('input[type="submit"][value*="予約"]')
                            if await continue_btn2.count() > 0:
                                await continue_btn2.first.click()
                                await page.wait_for_timeout(3000)

                                await save_page_info(page, "05_confirmation")

                                print("\n" + "=" * 60)
                                print("全ページの調査完了！")
                                print("=" * 60)

            input("\nEnterキーを押すとブラウザを閉じます...")

        except Exception as e:
            print(f"\nエラー: {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="ex_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
