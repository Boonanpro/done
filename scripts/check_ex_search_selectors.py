"""
SmartEX 検索フォームのセレクタ調査スクリプト

ログイン後の検索フォーム画面で、全ての要素を調査する
"""
import asyncio
import os
import sys
from pathlib import Path

# プロジェクトルートをPATHに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from dotenv import load_dotenv

from app.executors.ex_reservation.login import login, complete_otp_authentication
from app.executors.ex_reservation.selectors import MYPAGE

# .envファイルを読み込み
load_dotenv()

# 認証情報
MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")


async def get_otp_from_user() -> str:
    """OTP取得コールバック"""
    print("\n電話にOTPが届いているはずです")
    loop = asyncio.get_event_loop()
    otp_code = await loop.run_in_executor(
        None,
        lambda: input("OTPコード（6桁）を入力してください: ").strip()
    )
    return otp_code


async def main():
    print("=" * 60)
    print("SmartEX 検索フォームセレクタ調査")
    print("=" * 60)
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="ja-JP",
        )
        page = await context.new_page()

        try:
            # Step 1: ログイン
            print("ログイン中...")
            login_result = await login(page, MEMBER_ID, PASSWORD)

            if login_result.requires_otp:
                print("OTP認証が必要です\n")
                login_result = await complete_otp_authentication(page, get_otp_from_user)

            if not login_result.success:
                print(f"NG ログイン失敗: {login_result.message}")
                return

            print("OK ログイン成功\n")

            # Step 2: 検索フォームを開く
            print("検索フォームを開いています...")
            search_button = await page.query_selector(MYPAGE["search_train"])
            if search_button:
                await search_button.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
                print("OK 検索フォームを開きました\n")
            else:
                print("NG 検索ボタンが見つかりません")
                return

            # Step 3: セレクタ調査
            print("=" * 60)
            print("セレクタ調査開始")
            print("=" * 60)
            print()

            # 現在のURL
            print(f"現在のURL: {page.url}\n")

            # ===== SELECT要素を調査 =====
            print("-" * 60)
            print("SELECT要素（駅・時刻選択）")
            print("-" * 60)
            selects = await page.query_selector_all("select")
            for i, select in enumerate(selects):
                name = await select.get_attribute("name") or ""
                id_attr = await select.get_attribute("id") or ""
                class_attr = await select.get_attribute("class") or ""

                # 選択肢を取得
                options = await select.query_selector_all("option")
                option_count = len(options)
                first_options = []
                for j, opt in enumerate(options[:5]):  # 最初の5件
                    opt_text = await opt.inner_text()
                    opt_value = await opt.get_attribute("value") or ""
                    first_options.append(f"{opt_value}:{opt_text}")

                print(f"  [{i}] SELECT")
                print(f"      name={name}")
                print(f"      id={id_attr}")
                print(f"      class={class_attr}")
                print(f"      options={option_count}件")
                print(f"      最初の選択肢: {', '.join(first_options[:3])}")
                print()

            # ===== INPUT要素を調査 =====
            print("-" * 60)
            print("INPUT要素（ボタン・フォーム入力）")
            print("-" * 60)
            inputs = await page.query_selector_all("input")
            for i, inp in enumerate(inputs):
                inp_type = await inp.get_attribute("type") or ""
                name = await inp.get_attribute("name") or ""
                id_attr = await inp.get_attribute("id") or ""
                value = await inp.get_attribute("value") or ""
                class_attr = await inp.get_attribute("class") or ""

                if inp_type in ["submit", "button"] or value:
                    print(f"  [{i}] INPUT type={inp_type}")
                    print(f"      name={name}")
                    print(f"      id={id_attr}")
                    print(f"      value={value}")
                    print(f"      class={class_attr}")
                    print()

            # ===== BUTTON要素を調査 =====
            print("-" * 60)
            print("BUTTON要素")
            print("-" * 60)
            buttons = await page.query_selector_all("button")
            for i, btn in enumerate(buttons):
                text = await btn.inner_text()
                name = await btn.get_attribute("name") or ""
                id_attr = await btn.get_attribute("id") or ""
                class_attr = await btn.get_attribute("class") or ""
                btn_type = await btn.get_attribute("type") or ""

                print(f"  [{i}] BUTTON")
                print(f"      text={text}")
                print(f"      name={name}")
                print(f"      id={id_attr}")
                print(f"      type={btn_type}")
                print(f"      class={class_attr}")
                print()

            # ===== A要素（リンク）を調査 =====
            print("-" * 60)
            print("A要素（重要なリンク）")
            print("-" * 60)
            links = await page.query_selector_all("a")
            for i, link in enumerate(links):
                text = await link.inner_text()
                href = await link.get_attribute("href") or ""
                class_attr = await link.get_attribute("class") or ""

                # 空リンクやハッシュのみは除外
                if text.strip() and ("予約" in text or "検索" in text or "続ける" in text):
                    print(f"  [{i}] A")
                    print(f"      text={text}")
                    print(f"      href={href}")
                    print(f"      class={class_attr}")
                    print()

            # スクリーンショット保存
            screenshot_path = "screenshots/ex_search_form_debug.png"
            os.makedirs("screenshots", exist_ok=True)
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"\nスクリーンショット保存: {screenshot_path}")

            print("\n" + "=" * 60)
            print("調査完了")
            print("ブラウザを60秒間保持します（確認用）")
            print("=" * 60)
            await page.wait_for_timeout(60000)

        except Exception as e:
            print(f"\nエラー: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
