"""
SmartEX 全画面スキャン

ログイン後、全ての画面を巡回して要素情報を収集
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

from app.executors.ex_reservation.login import login, complete_otp_authentication, check_logged_in
from app.utils.session_manager import SessionManager

load_dotenv()

MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")


async def get_otp_from_user() -> str:
    """OTP取得"""
    print("\n電話にOTPが届いているはずです")
    loop = asyncio.get_event_loop()
    otp_code = await loop.run_in_executor(
        None,
        lambda: input("OTPコード（6桁）を入力してください: ").strip()
    )
    return otp_code


async def scan_page_elements(page, screen_name: str) -> dict:
    """
    ページの全要素をスキャン

    Args:
        page: Playwrightページ
        screen_name: 画面名（例: "search_form"）

    Returns:
        dict: 画面情報
    """
    print(f"\n{'='*60}")
    print(f"スキャン中: {screen_name}")
    print(f"{'='*60}")

    data = {
        "screen_name": screen_name,
        "url": page.url,
        "timestamp": datetime.now().isoformat(),
        "selects": [],
        "inputs": [],
        "buttons": [],
        "links": [],
    }

    # ===== SELECT要素 =====
    print("\n[1] SELECT要素を収集中...")
    selects = await page.query_selector_all("select")
    for i, select in enumerate(selects):
        name = await select.get_attribute("name") or ""
        id_attr = await select.get_attribute("id") or ""
        class_attr = await select.get_attribute("class") or ""

        # 選択肢を取得
        options = await select.query_selector_all("option")
        option_list = []
        for opt in options:
            opt_text = await opt.inner_text()
            opt_value = await opt.get_attribute("value") or ""
            option_list.append({"value": opt_value, "text": opt_text})

        select_data = {
            "index": i,
            "name": name,
            "id": id_attr,
            "class": class_attr,
            "options_count": len(option_list),
            "options": option_list[:10],  # 最初の10件のみ
        }
        data["selects"].append(select_data)
        print(f"  [{i}] SELECT name={name} id={id_attr} ({len(option_list)}件)")

    # ===== INPUT要素 =====
    print("\n[2] INPUT要素を収集中...")
    inputs = await page.query_selector_all("input")
    for i, inp in enumerate(inputs):
        inp_type = await inp.get_attribute("type") or ""
        name = await inp.get_attribute("name") or ""
        id_attr = await inp.get_attribute("id") or ""
        value = await inp.get_attribute("value") or ""
        class_attr = await inp.get_attribute("class") or ""
        placeholder = await inp.get_attribute("placeholder") or ""

        input_data = {
            "index": i,
            "type": inp_type,
            "name": name,
            "id": id_attr,
            "value": value,
            "class": class_attr,
            "placeholder": placeholder,
        }
        data["inputs"].append(input_data)

        if inp_type in ["submit", "button"] or value:
            print(f"  [{i}] INPUT type={inp_type} value={value} name={name}")

    # ===== BUTTON要素 =====
    print("\n[3] BUTTON要素を収集中...")
    buttons = await page.query_selector_all("button")
    for i, btn in enumerate(buttons):
        text = await btn.inner_text()
        name = await btn.get_attribute("name") or ""
        id_attr = await btn.get_attribute("id") or ""
        class_attr = await btn.get_attribute("class") or ""
        btn_type = await btn.get_attribute("type") or ""

        button_data = {
            "index": i,
            "text": text.strip(),
            "name": name,
            "id": id_attr,
            "type": btn_type,
            "class": class_attr,
        }
        data["buttons"].append(button_data)
        print(f"  [{i}] BUTTON text='{text.strip()}' type={btn_type}")

    # ===== 重要なリンク =====
    print("\n[4] 重要なリンクを収集中...")
    links = await page.query_selector_all("a")
    for i, link in enumerate(links):
        text = await link.inner_text()
        href = await link.get_attribute("href") or ""
        class_attr = await link.get_attribute("class") or ""

        # 重要なリンクのみ（空でない、ハッシュのみでない）
        if text.strip() and href and href != "#":
            link_data = {
                "index": i,
                "text": text.strip(),
                "href": href,
                "class": class_attr,
            }
            data["links"].append(link_data)
            if len(data["links"]) <= 20:  # 最初の20件のみ表示
                print(f"  [{i}] A text='{text.strip()[:30]}' href={href[:50]}")

    # スクリーンショット保存
    screenshot_path = f"screenshots/scan_{screen_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
    os.makedirs("screenshots", exist_ok=True)
    await page.screenshot(path=screenshot_path, full_page=True)
    data["screenshot"] = screenshot_path
    print(f"\nスクリーンショット: {screenshot_path}")

    return data


async def main():
    print("=" * 60)
    print("SmartEX 全画面スキャン")
    print("=" * 60)

    session_mgr = SessionManager("smartex")
    all_screens = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        context = await session_mgr.create_context(browser)
        page = await context.new_page()

        try:
            # ===== ログイン =====
            print("\n[ログイン処理]")
            await page.goto("https://shinkansen2.jr-central.co.jp/RSV_P/p7A/ClientService", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            is_logged_in = await check_logged_in(page)

            if not is_logged_in:
                print("ログインします...")
                login_result = await login(page, MEMBER_ID, PASSWORD)

                if login_result.requires_otp:
                    login_result = await complete_otp_authentication(page, get_otp_from_user)

                if not login_result.success:
                    print(f"NG ログイン失敗: {login_result.message}")
                    return

                await session_mgr.save_session(context)

            print("OK ログイン済み")

            # ===== 画面1: マイページ =====
            print("\n" + "=" * 60)
            print("画面1: マイページ")
            print("=" * 60)
            await page.goto("https://shinkansen2.jr-central.co.jp/RSV_P/p7A/ClientService", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            all_screens["mypage"] = await scan_page_elements(page, "mypage")

            # ===== 画面2: 検索フォーム =====
            print("\n" + "=" * 60)
            print("画面2: 検索フォーム")
            print("=" * 60)
            print("\n「列車を検索」をクリックして検索フォームを開きます...")

            # 列車を検索ボタンをクリック
            search_button = await page.query_selector('article:has-text("列車を検索")')
            if search_button:
                await search_button.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
                all_screens["search_form"] = await scan_page_elements(page, "search_form")
            else:
                print("NG 検索ボタンが見つかりません")

            # ===== 画面3: 検索結果（サンプル検索実行） =====
            print("\n" + "=" * 60)
            print("画面3: 検索結果")
            print("=" * 60)
            print("\nサンプル検索を実行します（東京→名古屋）...")

            # 簡単な検索条件を設定
            selects = await page.query_selector_all("select")
            if len(selects) >= 6:
                # 駅を選択（インデックスで指定）
                await selects[4].select_option(label="東 京")
                await selects[5].select_option(label="名古屋")
                await page.wait_for_timeout(1000)

                # 検索実行
                continue_btn = await page.query_selector('input[type="submit"][value*="予約"], button:has-text("予約")')
                if continue_btn:
                    await continue_btn.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await page.wait_for_timeout(3000)
                    all_screens["search_result"] = await scan_page_elements(page, "search_result")
                else:
                    print("NG 予約ボタンが見つかりません")

            # ===== 画面4: 座席選択（最初の候補を選択） =====
            print("\n" + "=" * 60)
            print("画面4: 座席選択")
            print("=" * 60)
            print("\n最初の候補を選択します...")

            # 「この候補を選択」をクリック
            select_buttons = await page.query_selector_all('paragraph:has-text("この候補を選択")')
            if select_buttons and len(select_buttons) > 0:
                await select_buttons[0].click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
                all_screens["seat_selection"] = await scan_page_elements(page, "seat_selection")
            else:
                print("候補選択ボタンが見つかりません")

            # ===== データ保存 =====
            output_file = f"ex_screens_data_{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(all_screens, f, ensure_ascii=False, indent=2)

            print("\n" + "=" * 60)
            print("スキャン完了")
            print("=" * 60)
            print(f"\n収集した画面数: {len(all_screens)}")
            print(f"データ保存先: {output_file}")

            for screen_name in all_screens:
                screen = all_screens[screen_name]
                print(f"\n■ {screen_name}")
                print(f"  URL: {screen['url']}")
                print(f"  SELECT: {len(screen['selects'])}件")
                print(f"  INPUT: {len(screen['inputs'])}件")
                print(f"  BUTTON: {len(screen['buttons'])}件")
                print(f"  スクリーンショット: {screen['screenshot']}")

            print("\n" + "=" * 60)
            print("ブラウザを30秒間保持します（確認用）")
            print("=" * 60)
            await page.wait_for_timeout(30000)

        except Exception as e:
            print(f"\nエラー: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
