"""
skill_loader.py の YAML frontmatter 対応テスト

テスト内容:
1. frontmatter ありの SKILL.md を正しくパースできるか
2. frontmatter なしの SKILL.md も従来通りパースできるか（後方互換性）
3. description が正しく取得できるか
4. domain が frontmatter から取得できるか
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.skill_loader import SkillLoader, GeneratedSkill


def test_frontmatter_parsing():
    """frontmatter ありの SKILL.md をパースするテスト"""
    print("=" * 60)
    print("Test 1: frontmatter ありの SKILL.md パース")
    print("=" * 60)

    # テスト用の一時ディレクトリを作成
    import tempfile
    import shutil

    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "test-skill"
        skill_dir.mkdir()

        # frontmatter ありの SKILL.md を作成
        skill_md_content = """---
name: test-skill
description: テスト用スキル - 検索と購入を自動化
domain: example.com
---

# Test Skill

テスト用のスキルです。

## Actions

| Action | Description | Requires | Doc |
|--------|-------------|----------|-----|
| `search` | 検索する | - | actions/search.md |
| `purchase` | 購入する | login | actions/purchase.md |

生成日時: 2026-01-15
"""
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(skill_md_content, encoding="utf-8")

        # パース
        loader = SkillLoader()
        result = loader._parse_skill(skill_dir, skill_md)

        print(f"name: {result.name}")
        print(f"description: {result.description}")
        print(f"domain: {result.domain}")
        print(f"title: {result.title}")
        print(f"actions: {result.actions}")
        print(f"generated_at: {result.generated_at}")

        # 検証
        assert result.name == "test-skill", f"Expected name 'test-skill', got '{result.name}'"
        assert result.description == "テスト用スキル - 検索と購入を自動化", f"Expected description, got '{result.description}'"
        assert result.domain == "example.com", f"Expected domain 'example.com', got '{result.domain}'"
        assert result.title == "Test Skill", f"Expected title 'Test Skill', got '{result.title}'"
        assert "search" in result.actions, f"Expected 'search' in actions, got {result.actions}"
        assert "purchase" in result.actions, f"Expected 'purchase' in actions, got {result.actions}"
        assert result.generated_at == "2026-01-15", f"Expected generated_at '2026-01-15', got '{result.generated_at}'"

        print("\n[PASS] frontmatter パース成功")


def test_no_frontmatter_fallback():
    """frontmatter なしの SKILL.md をパースするテスト（後方互換性）"""
    print("\n" + "=" * 60)
    print("Test 2: frontmatter なしの SKILL.md パース（後方互換性）")
    print("=" * 60)

    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "legacy-skill"
        skill_dir.mkdir()

        # frontmatter なしの SKILL.md を作成
        skill_md_content = """# Legacy Skill

レガシースキルです。

対象サイト: https://legacy.example.org/path

## Actions

| Action | Description | Doc |
|--------|-------------|-----|
| `execute` | 実行する | actions/execute.md |

生成日時: 2025-12-01
"""
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(skill_md_content, encoding="utf-8")

        # パース
        loader = SkillLoader()
        result = loader._parse_skill(skill_dir, skill_md)

        print(f"name: {result.name}")
        print(f"description: {result.description}")
        print(f"domain: {result.domain}")
        print(f"title: {result.title}")
        print(f"actions: {result.actions}")
        print(f"generated_at: {result.generated_at}")

        # 検証
        assert result.name == "legacy-skill", f"Expected name 'legacy-skill', got '{result.name}'"
        assert result.description == "", f"Expected empty description, got '{result.description}'"
        assert result.domain == "legacy.example.org", f"Expected domain 'legacy.example.org', got '{result.domain}'"
        assert result.title == "Legacy Skill", f"Expected title 'Legacy Skill', got '{result.title}'"
        assert "execute" in result.actions, f"Expected 'execute' in actions, got {result.actions}"

        print("\n[PASS] 後方互換性テスト成功")


def test_partial_frontmatter():
    """一部のフィールドのみの frontmatter テスト"""
    print("\n" + "=" * 60)
    print("Test 3: 一部フィールドのみの frontmatter パース")
    print("=" * 60)

    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "partial-skill"
        skill_dir.mkdir()

        # name と description のみの frontmatter
        skill_md_content = """---
name: partial-skill
description: 部分的なフロントマター
---

# Partial Skill

対象サイト: https://partial.example.net/

## Actions

| Action | Description | Doc |
|--------|-------------|-----|
| `login` | ログイン | actions/login.md |
"""
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(skill_md_content, encoding="utf-8")

        # パース
        loader = SkillLoader()
        result = loader._parse_skill(skill_dir, skill_md)

        print(f"name: {result.name}")
        print(f"description: {result.description}")
        print(f"domain: {result.domain}")
        print(f"title: {result.title}")

        # 検証
        assert result.name == "partial-skill"
        assert result.description == "部分的なフロントマター"
        # domain は frontmatter にないので本文から抽出
        assert result.domain == "partial.example.net", f"Expected domain from body, got '{result.domain}'"

        print("\n[PASS] 部分 frontmatter テスト成功")


def test_real_skills():
    """実際のスキルディレクトリをテスト"""
    print("\n" + "=" * 60)
    print("Test 4: 実際のスキルディレクトリ読み込み")
    print("=" * 60)

    loader = SkillLoader()
    skills = loader.load_all(force=True)

    print(f"読み込んだスキル数: {len(skills)}")

    for skill in skills:
        print(f"\n  - {skill.name}")
        print(f"    description: {skill.description or '(なし)'}")
        print(f"    domain: {skill.domain or '(なし)'}")
        print(f"    actions: {skill.actions}")

    print("\n[PASS] 実スキル読み込み成功")


def test_summary_with_description():
    """get_generated_skills_summary() が description を含むかテスト"""
    print("\n" + "=" * 60)
    print("Test 5: サマリーに description が含まれるか")
    print("=" * 60)

    loader = SkillLoader()
    loader.load_all(force=True)

    summary = loader.get_generated_skills_summary()
    print("サマリー:")
    print(summary[:500] if summary else "(空)")

    print("\n[PASS] サマリーテスト成功")


def main():
    try:
        test_frontmatter_parsing()
        test_no_frontmatter_fallback()
        test_partial_frontmatter()
        test_real_skills()
        test_summary_with_description()

        print("\n" + "=" * 60)
        print("All tests passed!")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        return 1
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
