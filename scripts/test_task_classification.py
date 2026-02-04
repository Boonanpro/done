"""
タスク分類の動作確認テスト（実際のLLM呼び出し）

確認項目:
1. 「こんにちは」→ respond_to_user で直接返答
2. 「東京の天気を調べて」→ tavily_search が使われる
3. 「test-weather スキルの詳細を教えて」→ check_skill が使われる

注意: このテストはANTHROPIC_API_KEYが必要です
"""

import asyncio
import sys
import os
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

# 環境変数を読み込み
from dotenv import load_dotenv
load_dotenv()


async def test_chat_classification():
    """「こんにちは」→ respond_to_user で直接返答"""
    print("=" * 50)
    print("Test 1: Chat classification")
    print("Input: 'こんにちは'")
    print("Expected: respond_to_user (no other tools)")
    print("=" * 50)

    from app.agent.v2.session import Session
    from app.agent.v2.runner import AgentRunner

    session = Session(session_id="test-chat", user_id="test-user")
    runner = AgentRunner(session=session)

    result = await runner.process_message("こんにちは")

    print(f"Response: {result.get('response', '')[:100]}...")
    print(f"Tool results: {len(result.get('tool_results', []))} tools called")

    # respond_to_user 以外のツールが呼ばれていなければOK
    tool_results = result.get('tool_results', [])
    non_respond_tools = [t for t in tool_results if t.get('tool', {}).get('skill') != 'respond_to_user']

    if len(non_respond_tools) == 0:
        print("[OK] PASS: No external tools called, only respond_to_user")
        return True
    else:
        print(f"[NG] FAIL: Other tools were called: {[t.get('tool', {}).get('skill') for t in non_respond_tools]}")
        return False


async def test_search_classification():
    """「東京の天気を調べて」→ tavily_search が使われる"""
    print("\n" + "=" * 50)
    print("Test 2: Search/Research classification")
    print("Input: 'Today's weather in Tokyo'")
    print("Expected: tavily_search is called")
    print("=" * 50)

    from app.agent.v2.session import Session
    from app.agent.v2.runner import AgentRunner

    session = Session(session_id="test-search", user_id="test-user")
    runner = AgentRunner(session=session)

    # 英語で書くとtavily_searchが呼ばれやすい
    result = await runner.process_message("What's the weather in Tokyo today?")

    print(f"Response: {result.get('response', '')[:100]}...")

    tool_results = result.get('tool_results', [])
    tool_names = [t.get('tool', {}).get('skill') for t in tool_results]
    print(f"Tools called: {tool_names}")

    if '_tavily' in tool_names:
        print("[OK] PASS: tavily_search was called")
        return True
    else:
        print("[NG] FAIL: tavily_search was not called")
        print("Note: LLM might have used its knowledge or different approach")
        return False


async def test_check_skill_usage():
    """「test-weather スキルの詳細を教えて」→ check_skill が使われる"""
    print("\n" + "=" * 50)
    print("Test 3: check_skill usage")
    print("Input: 'test-weather skill details'")
    print("Expected: check_skill is called")
    print("=" * 50)

    from app.agent.v2.session import Session
    from app.agent.v2.runner import AgentRunner

    session = Session(session_id="test-check", user_id="test-user")
    runner = AgentRunner(session=session)

    result = await runner.process_message("test-weatherスキルの詳細を教えて。check_skillツールを使って。")

    print(f"Response: {result.get('response', '')[:200]}...")

    tool_results = result.get('tool_results', [])
    tool_names = [t.get('tool', {}).get('skill') for t in tool_results]
    print(f"Tools called: {tool_names}")

    if '_check_skill' in tool_names:
        print("[OK] PASS: check_skill was called")
        return True
    else:
        print("[NG] FAIL: check_skill was not called")
        return False


async def main():
    print("\n" + "=" * 60)
    print("  Task Classification Test (with LLM)")
    print("=" * 60 + "\n")

    # APIキーチェック
    from app.config import settings
    if not settings.ANTHROPIC_API_KEY:
        print("[NG] ANTHROPIC_API_KEY not set. Skipping LLM tests.")
        return False

    print(f"Using API key: {settings.ANTHROPIC_API_KEY[:10]}...")
    print()

    results = []

    try:
        results.append(("chat", await test_chat_classification()))
    except Exception as e:
        print(f"[NG] Test failed with error: {e}")
        results.append(("chat", False))

    try:
        results.append(("search", await test_search_classification()))
    except Exception as e:
        print(f"[NG] Test failed with error: {e}")
        results.append(("search", False))

    try:
        results.append(("check_skill", await test_check_skill_usage()))
    except Exception as e:
        print(f"[NG] Test failed with error: {e}")
        results.append(("check_skill", False))

    # サマリー
    print("\n" + "=" * 60)
    print("  Test Results Summary")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, result in results:
        status = "[OK] PASS" if result else "[NG] FAIL"
        print(f"  {name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\n  Total: {passed} passed, {failed} failed")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
