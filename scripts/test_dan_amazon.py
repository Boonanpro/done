"""
ダンの視点でAmazonスキルをテスト

バックエンドのAgent v2経由でツール実行をテストし、
実際にダンが見ているエラーを確認する。
"""

import asyncio
import sys
import os
import io

# Windows コンソールの文字化け対策
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_tool_execution():
    """ダンと同じ方法でツール実行をテスト"""
    print("=" * 60)
    print("ダンの視点でAmazonスキルをテスト")
    print("=" * 60)

    from app.agent.v2.tools import execute_tool, SkillRegistry
    from app.executors.registry import register_all_executors

    # Executor登録（バックエンドと同じ）
    register_all_executors()

    # スキルをロード
    SkillRegistry.load()
    print(f"\nLoaded skills: {[s.name for s in SkillRegistry.list_all()]}")

    # ツール呼び出しをシミュレート
    tool_call = {
        "skill": "amazon",
        "action": "search",
        "params": {"query": "アベンヌウォーター 50ml", "quantity": 1},
    }

    print(f"\nExecuting: {tool_call}")
    print("-" * 60)

    try:
        result = await execute_tool(
            tool_call=tool_call,
            user_id="test-user-dan",
            credentials=None,  # 検索は認証不要
        )

        print(f"\n結果:")
        print(f"  success: {result.get('success')}")
        print(f"  error: {result.get('error')}")

        message = result.get('message', '')
        if message:
            print(f"  message: {message[:500]}...")

        if result.get('options'):
            print(f"  options: {len(result['options'])} items")
            for opt in result['options'][:2]:
                print(f"    - {opt}")

    except Exception as e:
        import traceback
        print(f"\n例外発生:")
        print(f"  {type(e).__name__}: {e}")
        traceback.print_exc()


async def test_executor_directly():
    """Executorを直接テスト（比較用）"""
    print("\n" + "=" * 60)
    print("Executor直接テスト（比較用）")
    print("=" * 60)

    from app.executors.amazon_executor import AmazonExecutor

    executor = AmazonExecutor(headed=False)

    print("\nExecuting: _do_search")
    print("-" * 60)

    try:
        result = await executor._do_search({
            "query": "アベンヌウォーター 50ml",
            "quantity": 1,
        })

        print(f"\n結果:")
        print(f"  success: {result.success}")
        print(f"  message: {result.message[:500] if result.message else 'None'}...")

    except Exception as e:
        import traceback
        print(f"\n例外発生:")
        print(f"  {type(e).__name__}: {e}")
        traceback.print_exc()


async def main():
    # テスト1: ダンと同じ方法（execute_tool経由）
    await test_tool_execution()

    # テスト2: Executor直接（比較用）
    # await test_executor_directly()


if __name__ == "__main__":
    asyncio.run(main())
