"""Progressive Disclosure 全フェーズ統合テスト"""

import sys
sys.path.insert(0, "D:/done")

from app.agent.v2.tools import SkillRegistry, convert_skill_to_tools, format_tool_result, get_all_skill_tools

def test_all_phases():
    """全フェーズの動作確認"""
    print("=" * 60)
    print("Progressive Disclosure 統合テスト")
    print("=" * 60)
    print()

    # Phase 1: frontmatterパース
    print("--- Phase 1: YAML Frontmatter ---")
    SkillRegistry.reload()
    skill = SkillRegistry.get("ex-reservation")

    assert skill is not None, "ex-reservation skill not found"
    assert skill.frontmatter.get("name") == "ex-reservation", "frontmatter.name mismatch"
    assert "Shinkansen" in skill.description, "description should contain 'Shinkansen'"
    assert skill.markdown_content.startswith("# EX"), "markdown_content should start with title"
    print(f"  [OK] name: {skill.name}")
    print(f"  [OK] description: {skill.description[:60]}...")
    print(f"  [OK] frontmatter keys: {list(skill.frontmatter.keys())}")
    print()

    # Phase 2: ツールdescription詳細化
    print("--- Phase 2: Tool Description ---")
    tools = convert_skill_to_tools(skill)

    search_tool = next((t for t in tools if "search" in t["name"]), None)
    assert search_tool is not None, "search tool not found"
    assert len(search_tool["description"]) > 100, "description should be detailed"
    print(f"  [OK] {search_tool['name']}")
    print(f"  [OK] description length: {len(search_tool['description'])} chars")
    print()

    # Phase 3: Progressive Disclosure
    print("--- Phase 3: Progressive Disclosure ---")
    result = {"success": True, "message": "Test result"}
    formatted = format_tool_result(result, "ex-reservation", "search", skill=skill)

    assert "## スキルマニュアル" in formatted.text, "Should have skill manual"
    assert "## search アクション詳細" in formatted.text, "Should have action manual"
    print(f"  [OK] tool_result length: {len(formatted.text)} chars")
    print(f"  [OK] Contains skill manual: Yes")
    print(f"  [OK] Contains action manual: Yes")
    print()

    # 後方互換性
    print("--- Backward Compatibility ---")
    formatted_no_skill = format_tool_result(result, "unknown", "action", skill=None)
    assert "## スキルマニュアル" not in formatted_no_skill.text, "Should not have manual without skill"
    print(f"  [OK] Works without skill object")
    print()

    # 全ツール数確認
    print("--- All Tools ---")
    all_tools = get_all_skill_tools()
    print(f"  Total tools: {len(all_tools)}")
    skill_tools = [t for t in all_tools if not t["name"].startswith(("respond", "visual", "tavily", "skill", "save"))]
    print(f"  Skill tools: {len(skill_tools)}")
    print()

    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)

if __name__ == "__main__":
    test_all_phases()
