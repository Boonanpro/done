"""Phase 1 動作確認: YAML frontmatterのパースと読み込み"""

import sys
sys.path.insert(0, "D:/done")

from app.agent.v2.tools import SkillRegistry, Skill

def test_frontmatter_parsing():
    """frontmatterが正しくパースされるか確認"""
    # スキルをリロード
    SkillRegistry.reload()

    # ex-reservationを取得
    skill = SkillRegistry.get("ex-reservation")

    print("=== ex-reservation ===")
    print(f"name: {skill.name}")
    print(f"display_name: {skill.display_name}")
    print(f"description: {skill.description[:100]}...")
    print(f"domain: {skill.domain}")
    print(f"frontmatter keys: {list(skill.frontmatter.keys())}")
    print(f"markdown_content starts with: {skill.markdown_content[:50]}...")
    print()

    # 検証
    assert skill.name == "ex-reservation", f"Expected 'ex-reservation', got '{skill.name}'"
    assert skill.frontmatter.get("name") == "ex-reservation", "frontmatter.name not found"
    assert "Shinkansen" in skill.description, "description should contain 'Shinkansen'"
    assert skill.domain == "smart-ex.jp", f"Expected 'smart-ex.jp', got '{skill.domain}'"
    assert skill.markdown_content.startswith("# EX予約"), "markdown_content should start with title"

    print("[OK] ex-reservation frontmatter parsing")

    # developerを取得
    skill2 = SkillRegistry.get("developer")

    print("=== developer ===")
    print(f"name: {skill2.name}")
    print(f"display_name: {skill2.display_name}")
    print(f"description: {skill2.description[:100]}...")
    print(f"frontmatter keys: {list(skill2.frontmatter.keys())}")
    print()

    assert skill2.name == "developer", f"Expected 'developer', got '{skill2.name}'"
    assert "debug" in skill2.description.lower(), "description should contain 'debug'"

    print("[OK] developer frontmatter parsing")

    print()
    print("=== Phase 1 テスト完了 ===")

if __name__ == "__main__":
    test_frontmatter_parsing()
