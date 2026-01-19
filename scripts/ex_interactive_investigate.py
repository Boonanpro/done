"""
EX 対話的調査

既存のログイン処理を使ってログイン後、各ページを調査
"""
import asyncio
import os
import sys
import json
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from dotenv import load_dotenv
from app.executors.ex_reservation.login import login, complete_otp_authentication

load_dotenv()

MEMBER_ID = os.getenv("EX_MEMBER_ID", "")
PASSWORD = os.getenv("EX_PASSWORD", "")


async def get_otp_from_file() -> str:
    """ファイルからOTPを取得"""
    otp_file = "otp_input.txt"

    print("\n" + "=" * 60)
    print("電話でOTPを取得したら、以下のコマンドを実行してください:")
    print(f"  echo OTPコード > {otp_file}")
    print("=" * 60)

    # 既存ファイル削除
    if os.path.exists(otp_file):
        os.remove(otp_file)

    # ファイルを監視（最大5分）
    for i in range(150):
        await asyncio.sleep(2)

        if os.path.exists(otp_file):
            try:
                with open(otp_file, 'r', encoding='utf-8') as f:
                    otp = f.read().strip()
                if otp and len(otp) == 6:
                    print(f"\nOTP受信: {otp}")
                    os.remove(otp_file)
                    return otp
            except:
                pass

        if i % 15 == 0:
            print(f"待機中... ({i*2}秒)")

    raise Exception("OTPタイムアウト")


async def investigate_page(page, page_name: str):
    """ページを調査"""
    print(f"\n{'=' * 60}")
    print(f"調査中: {page_name}")
    print(f"{'=' * 60}")

    url = page.url
    print(f"URL: {url}")

    # スクリーンショット
    screenshot = f"ex_{page_name}.png"
    await page.screenshot(path=screenshot, full_page=True)
    print(f"スクリーンショット: {screenshot}")

    # 要素カウント
    print("\n要素数:")
    print(f"  ボタン: {await page.locator('button, input[type=submit], input[type=button]').count()}")
    print(f"  リンク: {await page.locator('a').count()}")
    print(f"  セレクト: {await page.locator('select').count()}")
    print(f"  入力: {await page.locator('input').count()}")

    # HTML保存
    html_file = f"ex_{page_name}.html"
    content = await page.content()
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"HTML保存: {html_file}")


async def main():
    print("=" * 60)
    print("EX 対話的調査")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # ログイン
            print("\nログイン実行...")
            result = await login(page, MEMBER_ID, PASSWORD)

            if result.requires_otp:
                print("\nOTP認証が必要です")
                result = await complete_otp_authentication(page, get_otp_from_file)

            if not result.success:
                print(f"ログイン失敗: {result.message}")
                await page.screenshot(path="ex_login_error.png")
                return

            print("\nログイン成功！")

            # マイページ調査
            await investigate_page(page, "mypage")

            print("\n次の操作を待機中...")
            print("調査を続けるには指示をください")

            # ブラウザを保持
            await page.wait_for_timeout(600000)

        except Exception as e:
            print(f"\nエラー: {e}")
            import traceback
            traceback.print_exc()
            await page.screenshot(path="ex_error.png")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
