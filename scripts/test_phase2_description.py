"""Phase 2 動作確認: ツールdescriptionの詳細化"""

import sys
sys.path.insert(0, "D:/done")

from app.agent.v2.tools import SkillRegistry, convert_skill_to_tools

def test_tool_description():
    """ツールのdescriptionが詳細化されているか確認"""
    # スキルをリロード
    SkillRegistry.reload()

    # ex-reservationを取得
    skill = SkillRegistry.get("ex-reservation")
    tools = convert_skill_to_tools(skill)

    print("=== ex-reservation tools ===")
    for tool in tools:
        print(f"  {tool['name']}")
        print(f"    description: {tool['description'][:100]}...")
        print()

    # 検証
    search_tool = next((t for t in tools if "search" in t["name"]), None)
    assert search_tool is not None, "search tool not found"
    assert len(search_tool["description"]) > 100, "description should be detailed"
    assert "Shinkansen" in search_tool["description"], "description should contain skill info"

    print("[OK] ex-reservation tool description")

    # developerを取得
    skill2 = SkillRegistry.get("developer")
    tools2 = convert_skill_to_tools(skill2)

    print("=== developer tools ===")
    for tool in tools2[:3]:  # 最初の3つだけ表示
        print(f"  {tool['name']}")
        print(f"    description: {tool['description'][:80]}...")
        print()

    print(f"  ... and {len(tools2) - 3} more tools")

    print()
    print("=== Phase 2 test complete ===")

if __name__ == "__main__":
    test_tool_description()
