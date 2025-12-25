"""
HighwayBusExecutorの単純動作テスト
- タスク管理を使わず、純粋にブラウザ操作だけをテスト
"""
import asyncio
import sys
sys.path.insert(0, ".")

from app.executors.highway_bus_executor import HighwayBusExecutor
from app.tools.browser import get_page, cleanup_browser


async def test_browser_automation():
    """ブラウザ自動操作のテスト"""
    print("=" * 60)
    print("HighwayBusExecutor ブラウザ自動操作テスト")
    print("=" * 60)
    
    executor = HighwayBusExecutor()
    
    # テスト1: URL構築
    print("\n[TEST 1] URL構築")
    url = executor._build_search_url("大阪", "鳥取", "2025-12-23")
    print(f"  大阪->鳥取: {url}")
    
    # テスト2: ブラウザを開いてWILLERにアクセス
    print("\n[TEST 2] ブラウザ自動操作")
    print("  ブラウザを起動中...")
    
    page = await get_page()
    print("  [OK] ブラウザ起動成功")
    
    # WILLERにアクセス
    target_url = "https://travel.willer.co.jp/bus_search/osaka/all/tottori/all/"
    print(f"  アクセス中: {target_url}")
    
    await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
    print(f"  [OK] ページ読み込み完了")
    print(f"  タイトル: {await page.title()}")
    
    # 12/23の日付をクリック（あれば）
    await page.wait_for_timeout(2000)
    
    date_link = await page.query_selector('a:has-text("23")')
    if date_link:
        print("  12/23の日付リンクを発見")
        await date_link.click()
        await page.wait_for_timeout(2000)
        print("  [OK] 日付をクリック")
    
    # 「予約に進む」ボタンを探す
    book_button = await page.query_selector('a:has-text("予約に進む")')
    if book_button:
        print("  「予約に進む」ボタンを発見")
        await book_button.click()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)
        print(f"  [OK] 予約ページに遷移")
        print(f"  現在のURL: {page.url}")
    else:
        print("  「予約に進む」ボタンが見つかりません")
    
    # 現在のページタイトルを取得
    print(f"  最終ページタイトル: {await page.title()}")
    
    # 少し待ってからクリーンアップ
    print("\n5秒後にブラウザを閉じます...")
    await page.wait_for_timeout(5000)
    
    await cleanup_browser()
    print("[OK] テスト完了")


if __name__ == "__main__":
    asyncio.run(test_browser_automation())







