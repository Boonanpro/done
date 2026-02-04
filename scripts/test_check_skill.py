"""
check_skill ツールの動作確認テスト

確認項目:
1. parse_tool_name が check_skill を正しくパースするか
2. execute_tool で _check_skill が正しく処理されるか
3. SKILL.md + actions/*.md の内容が返されるか
"""

import asyncio
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agent.v2.tools import (
    parse_tool_name,
    execute_tool,
    get_all_skill_tools,
    SkillRegistry,
    CHECK_SKILL_TOOL,
)


def test_parse_tool_name():
    """parse_tool_name が check_skill を正しくパースするか"""
    print("=" * 50)
    print("Test 1: parse_tool_name('check_skill')")
    print("=" * 50)

    result = parse_tool_name("check_skill")
    print(f"Result: {result}")

    expected = ("_check_skill", "check")
    if result == expected:
        print("[OK] PASS")
        return True
    else:
        print(f"[NG] FAIL: expected {expected}")
        return False


def test_check_skill_tool_registered():
    """check_skill ツールが登録されているか"""
    print("\n" + "=" * 50)
    print("Test 2: check_skill in get_all_skill_tools()")
    print("=" * 50)

    tools = get_all_skill_tools()
    tool_names = [t["name"] for t in tools]
    print(f"Registered tools: {tool_names}")

    if "check_skill" in tool_names:
        print("[OK] PASS: check_skill is registered")
        return True
    else:
        print("[NG] FAIL: check_skill not found")
        return False


def test_check_skill_tool_definition():
    """CHECK_SKILL_TOOL の定義が正しいか"""
    print("\n" + "=" * 50)
    print("Test 3: CHECK_SKILL_TOOL definition")
    print("=" * 50)

    print(f"Name: {CHECK_SKILL_TOOL['name']}")
    print(f"Description: {CHECK_SKILL_TOOL['description'][:100]}...")
    print(f"Required params: {CHECK_SKILL_TOOL['input_schema'].get('required', [])}")

    if CHECK_SKILL_TOOL["name"] == "check_skill":
        print("[OK] PASS")
        return True
    else:
        print("[NG] FAIL")
        return False


async def test_execute_check_skill_valid():
    """存在するスキルで check_skill を実行"""
    print("\n" + "=" * 50)
    print("Test 4: execute_tool with valid skill (test-weather)")
    print("=" * 50)

    tool_call = {
        "tool_use_id": "test-123",
        "skill": "_check_skill",
        "action": "check",
        "params": {"skill_name": "test-weather"},
    }

    result = await execute_tool(
        tool_call=tool_call,
        user_id="test-user",
    )

    print(f"Success: {result.get('success')}")
    print(f"Skill name: {result.get('skill_name')}")
    print(f"Display name: {result.get('display_name')}")
    print(f"Available actions: {result.get('available_actions')}")

    if result.get("manual"):
        print(f"Manual length: {len(result['manual'])} chars")
        print(f"Manual preview:\n{result['manual'][:500]}...")

    if result.get("success"):
        print("[OK] PASS")
        return True
    else:
        print(f"[NG] FAIL: {result.get('error')}")
        return False


async def test_execute_check_skill_invalid():
    """存在しないスキルで check_skill を実行"""
    print("\n" + "=" * 50)
    print("Test 5: execute_tool with invalid skill")
    print("=" * 50)

    tool_call = {
        "tool_use_id": "test-456",
        "skill": "_check_skill",
        "action": "check",
        "params": {"skill_name": "nonexistent-skill"},
    }

    result = await execute_tool(
        tool_call=tool_call,
        user_id="test-user",
    )

    print(f"Success: {result.get('success')}")
    print(f"Error: {result.get('error')}")

    if not result.get("success") and "存在しません" in result.get("error", ""):
        print("[OK] PASS: Correctly returned error for nonexistent skill")
        return True
    else:
        print("[NG] FAIL: Should have returned error")
        return False


def test_skill_registry():
    """SkillRegistry がスキルを正しく読み込むか"""
    print("\n" + "=" * 50)
    print("Test 6: SkillRegistry.list_all()")
    print("=" * 50)

    SkillRegistry.reload()
    skills = SkillRegistry.list_all()

    print(f"Found {len(skills)} skills:")
    for skill in skills:
        print(f"  - {skill.name}: {skill.description[:50] if skill.description else '(no description)'}...")

    if len(skills) > 0:
        print("[OK] PASS")
        return True
    else:
        print("[NG] FAIL: No skills found")
        return False


async def main():
    print("\n" + "=" * 60)
    print("  check_skill ツール動作確認テスト")
    print("=" * 60 + "\n")

    results = []

    # 同期テスト
    results.append(("parse_tool_name", test_parse_tool_name()))
    results.append(("tool_registered", test_check_skill_tool_registered()))
    results.append(("tool_definition", test_check_skill_tool_definition()))
    results.append(("skill_registry", test_skill_registry()))

    # 非同期テスト
    results.append(("execute_valid", await test_execute_check_skill_valid()))
    results.append(("execute_invalid", await test_execute_check_skill_invalid()))

    # サマリー
    print("\n" + "=" * 60)
    print("  テスト結果サマリー")
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
