"""新スキル追加の容易さを確認するテスト"""

import sys
sys.path.insert(0, "D:/done")

from app.agent.v2.tools import SkillRegistry, convert_skill_to_tools, format_tool_result

def test_new_skill():
    """SKILL.mdだけで新スキルが動作するか確認"""
    print("=== 新スキル登録テスト ===")
    print()

    # スキルをリロード
    SkillRegistry.reload()

    # test-dummyを取得
    skill = SkillRegistry.get("test-dummy")

    if skill is None:
        print("[FAIL] test-dummy skill not found!")
        return False

    print("1. スキル読み込み")
    print(f"   name: {skill.name}")
    print(f"   display_name: {skill.display_name}")
    print(f"   description: {skill.description[:50]}...")
    print(f"   frontmatter: {list(skill.frontmatter.keys())}")
    print()

    # ツール定義が生成されるか
    tools = convert_skill_to_tools(skill)
    print("2. ツール定義生成")
    for tool in tools:
        print(f"   {tool['name']}: {tool['description'][:60]}...")
    print()

    # format_tool_resultでスキル本文が注入されるか
    result = {"success": True, "message": "Test OK"}
    formatted = format_tool_result(result, "test-dummy", "verify", skill=skill)

    print("3. Progressive Disclosure")
    has_skill_manual = "## スキルマニュアル" in formatted.text
    has_action_manual = "## verify アクション詳細" in formatted.text
    print(f"   スキル本文注入: {'OK' if has_skill_manual else 'NG'}")
    print(f"   アクションマニュアル注入: {'OK' if has_action_manual else 'NG'}")
    print(f"   tool_result長さ: {len(formatted.text)} chars")
    print()

    # 結果
    success = skill is not None and len(tools) > 0 and has_skill_manual and has_action_manual
    print("=" * 40)
    if success:
        print("結論: SKILL.mdだけで新スキルが完全に動作する")
        print("      コード変更不要")
    else:
        print("結論: 一部機能が動作していない")
    print("=" * 40)

    return success

if __name__ == "__main__":
    test_new_skill()
