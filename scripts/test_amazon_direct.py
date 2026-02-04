"""
Amazon スキル直接テスト

HTTPレイヤーをバイパスしてAgent v2のツール実行を直接テスト

使用方法:
    python scripts/test_amazon_direct.py
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


async def test_skill_registry():
    """SkillRegistryの確認"""
    print("=" * 60)
    print("Test 1: SkillRegistry")
    print("=" * 60)

    from app.agent.v2.tools import SkillRegistry

    SkillRegistry.load()

    skills = SkillRegistry.list_all()
    print(f"\nLoaded {len(skills)} skills:")
    for skill in skills:
        print(f"  - {skill.name}: {skill.display_name}")
        actions = skill.list_available_actions()
        print(f"    Actions: {actions}")

    # Amazonスキルを確認
    amazon = SkillRegistry.get("amazon")
    if amazon:
        print(f"\n✓ Amazon skill loaded")
        print(f"  Service type: {amazon.service_type}")
        print(f"  Service name: {amazon.service_name}")
        print(f"  Actions: {amazon.list_available_actions()}")
        return True
    else:
        print(f"\n✗ Amazon skill NOT found!")
        return False


async def test_tool_parsing():
    """ツール呼び出しのパースをテスト"""
    print("\n" + "=" * 60)
    print("Test 2: Tool Parsing")
    print("=" * 60)

    from app.agent.v2.tools import parse_tool_call

    test_cases = [
        "[TOOL: amazon search]\nquery: アベンヌウォーター 50ml",
        "[TOOL: amazon add_to_cart]\nasin: B015KMYMQ0\nquantity: 2",
        "[TOOL: amazon order_history]",
    ]

    for test in test_cases:
        result = parse_tool_call(test)
        print(f"\nInput: {test}")
        if result:
            print(f"  ✓ Parsed:")
            print(f"    Skill: {result['skill']}")
            print(f"    Action: {result['action']}")
            print(f"    Params: {result['params']}")
        else:
            print(f"  ✗ Parse failed")

    return True


async def test_executor_import():
    """Executorのインポートをテスト"""
    print("\n" + "=" * 60)
    print("Test 3: Executor Import")
    print("=" * 60)

    try:
        from app.executors.amazon_executor import AmazonExecutor
        print(f"✓ AmazonExecutor imported successfully")

        # インスタンス作成
        executor = AmazonExecutor(headed=True)
        print(f"✓ AmazonExecutor instance created")
        print(f"  Methods: {[m for m in dir(executor) if not m.startswith('_')]}")

        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_tool_execution():
    """実際のツール実行をテスト（headed モードでブラウザ表示）"""
    print("\n" + "=" * 60)
    print("Test 4: Tool Execution (Browser)")
    print("=" * 60)

    from app.agent.v2.tools import execute_tool
    from app.executors.registry import register_all_executors

    # Executor登録
    register_all_executors()

    # 検索を実行
    print("\nExecuting: amazon search query='アベンヌウォーター 50ml'")
    print("(Browser will open in headed mode)")

    result = await execute_tool(
        skill_name="amazon",
        action="search",
        params={"query": "アベンヌウォーター 50ml", "quantity": 1},
        user_id="test-user",
        credentials={},  # 空（認証不要の操作）
    )

    print(f"\nResult:")
    print(f"  Success: {result.get('success')}")
    print(f"  Message: {result.get('message', '')[:200]}...")

    if result.get('options'):
        print(f"\n  Options found: {len(result['options'])}")
        for opt in result['options'][:3]:
            print(f"    - {opt.get('title', '')[:50]}")
            print(f"      Price: {opt.get('price')}")
            print(f"      URL: {opt.get('url', '')[:60]}...")

    return result.get('success', False)


async def main():
    print("Amazon Skill Direct Integration Test")
    print("=" * 60)

    # Test 1: SkillRegistry
    if not await test_skill_registry():
        print("\n❌ SkillRegistry test failed - stopping")
        return

    # Test 2: Tool Parsing
    await test_tool_parsing()

    # Test 3: Executor Import
    if not await test_executor_import():
        print("\n❌ Executor import test failed - stopping")
        return

    # Test 4: Actual Execution (skip if --no-browser flag)
    if "--no-browser" not in sys.argv:
        print("\n⚠️  This test will open a browser window")
        print("   Add --no-browser flag to skip")
        input("   Press Enter to continue...")

        if await test_tool_execution():
            print("\n✅ All tests passed!")
        else:
            print("\n⚠️  Tool execution returned failure (may be expected)")
    else:
        print("\n⏭️  Skipping browser test")
        print("✅ All non-browser tests passed!")


if __name__ == "__main__":
    asyncio.run(main())
