"""
HighwayBusExecutorの実動作テスト

このスクリプトはHighwayBusExecutorを実際に動かして、
WILLERサイトでバス検索ができるかテストします。
"""
import asyncio
import sys
sys.path.insert(0, ".")

from app.executors.highway_bus_executor import HighwayBusExecutor
from app.models.schemas import SearchResult
from app.tools.browser import cleanup_browser


async def test_highway_bus_executor():
    """HighwayBusExecutorの実動作テスト"""
    print("=" * 60)
    print("HighwayBusExecutor 実動作テスト開始")
    print("=" * 60)
    
    # Executorを作成
    executor = HighwayBusExecutor()
    print(f"\n[OK] Executor作成成功: {executor.service_name}")
    print(f"   URL一覧: {list(executor.URLS.keys())}")
    
    # テスト1: 検索URLの構築
    print("\n--- テスト1: 検索URLの構築 ---")
    test_cases = [
        ("大阪", "米子", "2025-12-23"),
        ("東京", "大阪", ""),
        ("名古屋", "福岡", "2025-01-15"),
    ]
    
    for dep, arr, date in test_cases:
        url = executor._build_search_url(dep, arr, date)
        print(f"   {dep}→{arr} ({date or '日付なし'}): {url}")
    
    # テスト2: 実際にブラウザを開いてWILLERにアクセス
    print("\n--- テスト2: 実サイトアクセス ---")
    print("   ブラウザを起動してWILLERサイトにアクセスします...")
    
    # SearchResultを作成（シンプルなテストデータ）
    search_result = SearchResult(
        id="test-001",
        service_name="willer",
        category="bus",
        title="大阪→米子 高速バス",
        url="https://travel.willer.co.jp/bus_search/osaka/all/tottori/all/",
        details={
            "departure": "大阪",
            "arrival": "米子",
            "date": "2025-12-23",
        }
    )
    
    try:
        # _do_executeを呼び出し（認証情報なしなのでログインは失敗するはず）
        result = await executor._do_execute(
            task_id="test-task-001",
            search_result=search_result,
            credentials=None,  # ログイン情報なし
        )
        
        print(f"\n   実行結果:")
        print(f"   - 成功: {result.success}")
        print(f"   - メッセージ: {result.message}")
        if result.details:
            print(f"   - 詳細: {result.details}")
            
    except Exception as e:
        print(f"\n   [ERROR] エラー発生: {type(e).__name__}: {e}")
    
    finally:
        # ブラウザをクリーンアップ
        print("\n--- クリーンアップ ---")
        await cleanup_browser()
        print("   ブラウザを閉じました")
    
    print("\n" + "=" * 60)
    print("テスト完了")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_highway_bus_executor())







