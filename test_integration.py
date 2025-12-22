"""
統合テスト：チャット→Executor連携の確認
"""
import asyncio
import sys
sys.path.insert(0, ".")

from app.executors.highway_bus_executor import HighwayBusExecutor
from app.executors.base import ExecutorFactory
from app.agent.agent import AISecretaryAgent
from app.models.schemas import TaskType


async def test_url_construction():
    """URL構築のテスト（地名辞書拡張確認）"""
    print("=" * 60)
    print("[TEST 1] URL構築テスト")
    print("=" * 60)
    
    executor = HighwayBusExecutor()
    
    test_cases = [
        ("大阪", "米子", "2025-12-23"),
        ("梅田", "鳥取", "2025-12-23"),
        ("東京", "大阪", ""),
        ("名古屋", "福岡", "2025-01-15"),
        ("新宿", "仙台", ""),
    ]
    
    all_passed = True
    for dep, arr, date in test_cases:
        url = executor._build_search_url(dep, arr, date)
        # 出発地と到着地が正しくマッピングされているか確認
        is_valid = "tokyo/all/tokyo" not in url and "osaka/all/osaka" not in url
        status = "[OK]" if is_valid else "[NG]"
        if not is_valid:
            all_passed = False
        print(f"  {status} {dep}->{arr}: {url}")
    
    return all_passed


async def test_executor_factory():
    """ExecutorFactoryのテスト"""
    print("\n" + "=" * 60)
    print("[TEST 2] ExecutorFactoryテスト")
    print("=" * 60)
    
    # バスExecutor
    bus_executor = ExecutorFactory.get_executor("bus", "willer")
    print(f"  [OK] bus executor: {type(bus_executor).__name__}")
    
    # 電車Executor
    train_executor = ExecutorFactory.get_executor("train", "ex_reservation")
    print(f"  [OK] train executor: {type(train_executor).__name__}")
    
    # 商品Executor
    product_executor = ExecutorFactory.get_executor("product", "amazon")
    print(f"  [OK] product executor: {type(product_executor).__name__}")
    
    return True


async def test_agent_task_flow():
    """AIエージェントのタスクフローテスト（実行なし）"""
    print("\n" + "=" * 60)
    print("[TEST 3] AIエージェント タスクフローテスト")
    print("=" * 60)
    
    # エージェントを作成（ツールなし）
    agent = AISecretaryAgent(tool_names=[])
    
    # 願望を処理（実際のAPI呼び出しをするので時間がかかる）
    print("  願望を処理中: '梅田から米子まで高速バスを予約したい'")
    print("  (AIが提案を生成中...)")
    
    try:
        result = await agent.process_wish(
            wish="梅田から米子まで高速バスを予約したい",
            user_id="test-user",
        )
        
        print(f"  [OK] タスクID: {result['task_id']}")
        print(f"  [OK] 確認が必要: {result['requires_confirmation']}")
        print(f"  [OK] 提案アクション数: {len(result['proposed_actions'])}")
        
        # タスクが保存されているか確認
        task = await agent.get_task(result['task_id'])
        if task:
            print(f"  [OK] タスク保存確認: status={task.status}")
        else:
            print("  [NG] タスクが保存されていません")
            return False
        
        return True
        
    except Exception as e:
        print(f"  [NG] エラー: {e}")
        return False


async def test_execute_task_structure():
    """execute_taskの構造テスト（実際の実行はしない）"""
    print("\n" + "=" * 60)
    print("[TEST 4] execute_task構造テスト")
    print("=" * 60)
    
    agent = AISecretaryAgent(tool_names=[])
    
    # ダミータスクを直接登録
    from datetime import datetime
    from app.models.schemas import TaskStatus
    
    task_id = "test-structure-001"
    AISecretaryAgent._tasks[task_id] = {
        "id": task_id,
        "user_id": "test-user",
        "type": TaskType.TRAVEL,
        "status": TaskStatus.PROPOSED,
        "original_wish": "梅田から米子まで高速バスを予約したい",
        "proposed_actions": ["WILLERで予約"],
        "execution_result": None,
        "search_results": [],
        "created_at": datetime.utcnow(),
    }
    
    print(f"  ダミータスク登録: {task_id}")
    
    # execute_taskを呼び出し（Executorは動くが、認証情報がないのでログインで止まるはず）
    print("  execute_taskを呼び出し中...")
    print("  (ブラウザが起動します - 認証情報がないのでログイン要求で止まります)")
    
    try:
        result = await agent.execute_task(task_id)
        print(f"  [OK] 実行結果: status={result.get('status')}")
        if result.get('result'):
            print(f"  [OK] メッセージ: {result['result'].get('message', 'N/A')[:50]}...")
        return True
    except Exception as e:
        print(f"  [NG] エラー: {e}")
        return False


async def main():
    """メインテスト実行"""
    print("\n" + "=" * 60)
    print("統合テスト開始")
    print("=" * 60)
    
    results = []
    
    # テスト1: URL構築
    results.append(("URL構築", await test_url_construction()))
    
    # テスト2: ExecutorFactory
    results.append(("ExecutorFactory", await test_executor_factory()))
    
    # テスト3: AIエージェントタスクフロー（時間がかかるのでスキップ可能）
    # results.append(("AIエージェント", await test_agent_task_flow()))
    
    # テスト4: execute_task構造（ブラウザ起動するのでスキップ可能）
    # results.append(("execute_task", await test_execute_task_structure()))
    
    # 結果サマリー
    print("\n" + "=" * 60)
    print("テスト結果サマリー")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        if not passed:
            all_passed = False
        print(f"  {status} {name}")
    
    print("\n" + ("全テスト成功!" if all_passed else "一部テスト失敗"))
    
    return all_passed


if __name__ == "__main__":
    asyncio.run(main())

