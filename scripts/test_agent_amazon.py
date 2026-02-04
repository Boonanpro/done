"""
Agent v2 Amazon統合テスト

Amazonスキルがエージェント経由で動作するかを確認。
"""

import asyncio
import sys
import uuid
sys.path.insert(0, "D:\\done")

from app.agent.v2.runner import create_runner


async def test_amazon_search():
    """Amazon検索の統合テスト"""
    print("=" * 60)
    print("Agent v2 Amazon統合テスト")
    print("=" * 60)

    async def on_step(step: str):
        # 絵文字を除去してエンコードエラーを回避
        safe_step = step.encode('ascii', 'ignore').decode('ascii')
        print(f"  [STEP] {safe_step[:100]}...")

    # テスト用UUID
    test_user_id = str(uuid.uuid4())
    test_session_id = str(uuid.uuid4())

    runner = await create_runner(
        session_id=test_session_id,
        user_id=test_user_id,
        on_reasoning_step=on_step,
    )

    # Amazon検索をリクエスト
    message = "Amazonでアベンヌウォーター 50mlを検索して"
    print(f"\nUser: {message}")
    print()

    result = await runner.process_message(message)

    print(f"\n--- 結果 ---")
    print(f"State: {result['state']}")
    print(f"Response:\n{result['response'][:500]}...")

    if result.get("tool_results"):
        print(f"\nTool executed:")
        for tr in result["tool_results"]:
            print(f"   {tr['tool']['skill']} {tr['tool']['action']}")
            success = tr['result'].get('success') if isinstance(tr['result'], dict) else 'N/A'
            print(f"   success: {success}")

    # 結果をファイルに保存
    with open("amazon_agent_test_result.txt", "w", encoding="utf-8") as f:
        f.write(f"State: {result['state']}\n\n")
        f.write(f"Response:\n{result['response']}\n\n")
        if result.get("tool_results"):
            f.write("Tool Results:\n")
            for tr in result["tool_results"]:
                f.write(f"  {tr['tool']}\n")

    print("\n結果を amazon_agent_test_result.txt に保存しました")

    return result


if __name__ == "__main__":
    asyncio.run(test_amazon_search())
