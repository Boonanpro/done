"""
Amazon スキル デバッグテスト

問題の特定：
1. LLMの出力を確認 (raw_response)
2. parse_tool_callの結果を確認
3. execute_toolのデバッグ出力を確認
"""

import asyncio
import sys
import uuid
sys.path.insert(0, "D:\\done")

from app.agent.v2.runner import create_runner
from app.agent.v2.tools import parse_tool_call, SkillRegistry


async def test_amazon_debug():
    """Amazon検索のデバッグテスト"""
    print("=" * 60)
    print("Amazon スキル デバッグテスト")
    print("=" * 60)

    # 1. まずスキル登録状況を確認
    print("\n--- 1. スキル登録状況 ---")
    SkillRegistry.load()
    skills = SkillRegistry.list_all()
    for skill in skills:
        print(f"  - {skill.name}: service_type={skill.service_type}, service_name={skill.service_name}")

    amazon_skill = SkillRegistry.get("amazon")
    if amazon_skill:
        print(f"\n  Amazon skill found: {amazon_skill.name}")
        print(f"    service_type: {amazon_skill.service_type}")
        print(f"    service_name: {amazon_skill.service_name}")
    else:
        print("\n  WARNING: Amazon skill NOT found!")

    # 2. parse_tool_call のテスト
    print("\n--- 2. parse_tool_call テスト ---")
    test_responses = [
        "[TOOL: amazon search]\nquery: テスト商品",
        "[TOOL: amazon search]\nquery: アベンヌウォーター 50ml",
        "[TOOL: ex-reservation search]\ndeparture: 東京\narrival: 新大阪",
    ]
    for response in test_responses:
        result = parse_tool_call(response)
        print(f"\n  Input: {response[:50]}...")
        print(f"  Result: {result}")

    # 3. エージェント統合テスト
    print("\n--- 3. エージェント統合テスト ---")

    async def on_step(step: str):
        safe_step = step.encode('ascii', 'ignore').decode('ascii')
        print(f"  [STEP] {safe_step[:80]}...")

    test_user_id = str(uuid.uuid4())
    test_session_id = str(uuid.uuid4())

    runner = await create_runner(
        session_id=test_session_id,
        user_id=test_user_id,
        on_reasoning_step=on_step,
    )

    message = "Amazonでアベンヌウォーター 50mlを検索して"
    print(f"\nUser: {message}")
    print("\n処理中...")

    result = await runner.process_message(message)

    print(f"\n--- 結果 ---")
    print(f"State: {result['state']}")
    print(f"\nResponse (first 500 chars):\n{result['response'][:500]}")

    # raw_response を確認
    if result.get("raw_response"):
        print(f"\n--- LLM raw_response (最初の1000文字) ---")
        raw = result["raw_response"][:1000]
        print(raw)

        # parse_tool_call で解析
        tool_call = parse_tool_call(result["raw_response"])
        print(f"\n--- parse_tool_call結果 ---")
        print(f"tool_call: {tool_call}")
    else:
        print("\nWARNING: raw_response not found in result")

    if result.get("tool_results"):
        print(f"\n--- Tool Results ---")
        for tr in result["tool_results"]:
            print(f"  Tool: {tr['tool']}")
            res = tr['result']
            if isinstance(res, dict):
                print(f"  Success: {res.get('success')}")
                print(f"  Error type: {res.get('error_type')}")
                print(f"  Message: {str(res.get('message', ''))[:200]}")
    else:
        print("\nNo tool_results found (possibly credentials_required)")

    if result.get("credentials_required"):
        print(f"\n--- Credentials Required ---")
        print(f"  Service: {result.get('service')}")
        print(f"  Fields: {result.get('fields')}")

    # 結果をファイルに保存
    with open("amazon_debug_result.txt", "w", encoding="utf-8") as f:
        f.write(f"State: {result['state']}\n\n")
        f.write(f"Response:\n{result['response']}\n\n")
        if result.get("raw_response"):
            f.write(f"Raw Response:\n{result['raw_response']}\n\n")
        f.write(f"Credentials Required: {result.get('credentials_required')}\n")
        f.write(f"Service: {result.get('service')}\n")

    print("\n結果を amazon_debug_result.txt に保存しました")


if __name__ == "__main__":
    asyncio.run(test_amazon_debug())
