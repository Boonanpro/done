"""
スクロール動作の目視確認テスト

ブラウザを開いたまま、スクロールが実際に動いているか確認する。
各ステップで5秒待機して目視確認できるようにする。
"""

import asyncio
import sys
sys.path.insert(0, "D:/done")

from app.tools.browser import get_executor_page, close_executor_browser


async def test_scroll_visual():
    print("=" * 60)
    print("スクロール目視確認テスト")
    print("=" * 60)

    page = await get_executor_page()

    # Step 1: Amazonを開く
    print("\n1. Amazonを開きます...")
    await page.goto("https://www.amazon.co.jp")
    print("   → 5秒待機（ページを確認してください）")
    await page.wait_for_timeout(5000)

    # Step 2: ボット検知を突破して検索
    print("\n2. 検索します...")

    # 最大3回試行
    for attempt in range(3):
        search_box = page.locator('#twotabsearchtextbox')
        if await search_box.count() > 0:
            try:
                is_visible = await search_box.is_visible()
                if is_visible:
                    print(f"   検索ボックス発見！")
                    await search_box.fill("アベンヌウォーター")
                    await page.keyboard.press("Enter")
                    print("   → 5秒待機（検索結果を確認してください）")
                    await page.wait_for_timeout(5000)
                    break
            except:
                pass

        print(f"   試行 {attempt + 1}: 検索ボックスが見つかりません。ボット検知ページをチェック...")

        # ボット検知ボタンをクリック
        btn = page.locator('input[type="submit"]')
        if await btn.count() > 0:
            print("   ボタン発見！クリックします...")
            await btn.click()
            await page.wait_for_timeout(3000)
        else:
            await page.wait_for_timeout(2000)

    # 検索結果ページにいるか確認
    current_url = await page.evaluate("window.location.href")
    print(f"   現在のURL: {current_url[:80]}...")

    # Step 3: スクロールテスト（3回）
    for i in range(5):
        print(f"\n3-{i+1}. スクロールします（600px下へ）...")

        # 現在のスクロール位置を取得
        scroll_before = await page.evaluate("window.scrollY")
        print(f"   スクロール前: {scroll_before}px")

        # スクロール実行
        await page.evaluate("window.scrollBy(0, 600)")

        # スクロール後の位置を確認
        scroll_after = await page.evaluate("window.scrollY")
        print(f"   スクロール後: {scroll_after}px")
        print(f"   差分: {scroll_after - scroll_before}px")

        print("   → 3秒待機（スクロールを確認してください）")
        await page.wait_for_timeout(3000)

    print("\n" + "=" * 60)
    print("テスト完了！")
    print("10秒後にブラウザを閉じます...")
    print("=" * 60)
    await page.wait_for_timeout(10000)

    await close_executor_browser()


if __name__ == "__main__":
    asyncio.run(test_scroll_visual())
