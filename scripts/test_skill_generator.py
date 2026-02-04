"""
SkillGenerator のテスト
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.skill_generator import SkillGenerator, generate_skill_from_yaml


def test_load_session():
    """セッション読み込みテスト"""
    print("=== セッション読み込みテスト ===")

    generator = SkillGenerator()

    # 成功したセッションを読み込む
    yaml_path = Path("D:/done/app/logs/browser/dcf085dd/20260125_163729_楽天市場で「アベンヌウォーター」を検索して、検索結果を確認す.yaml")

    session = generator.load_session(yaml_path)

    print(f"Session ID: {session.id}")
    print(f"Task: {session.task}")
    print(f"Site: {session.site}")
    print(f"Success: {session.success}")
    print(f"Steps count: {len(session.steps)}")

    for step in session.steps:
        print(f"  Step {step.index}: {step.action} -> {step.result.get('success', False)}")

    return session


def test_suggest_skill_name():
    """スキル名推測テスト"""
    print("\n=== スキル名推測テスト ===")

    generator = SkillGenerator()
    session = test_load_session()

    skill_name = generator.suggest_skill_name(session)
    print(f"Suggested skill name: {skill_name}")

    return skill_name


def test_generate_skill():
    """スキル生成テスト"""
    print("\n=== スキル生成テスト ===")

    generator = SkillGenerator()

    yaml_path = Path("D:/done/app/logs/browser/dcf085dd/20260125_163729_楽天市場で「アベンヌウォーター」を検索して、検索結果を確認す.yaml")
    session = generator.load_session(yaml_path)

    skill = generator.from_session(session)

    print(f"Skill name: {skill.name}")
    print(f"Site: {skill.site}")
    print(f"Description: {skill.description}")
    print(f"\n--- SKILL.md ---")
    print(skill.skill_md)

    print(f"\n--- Actions ({len(skill.actions)}) ---")
    for action_name, content in skill.actions.items():
        print(f"\n[{action_name}.md]")
        print(content[:500])

    print(f"\n--- Selectors ({len(skill.selectors)}) ---")
    for name, hint in skill.selectors.items():
        print(f"  {name}: {hint}")

    return skill


def test_save_skill():
    """スキル保存テスト（テスト用ディレクトリに保存）"""
    print("\n=== スキル保存テスト ===")

    # テスト用のスキルディレクトリを使用
    test_skills_dir = Path("D:/done/.claude/skills/_test_generated")
    generator = SkillGenerator(skills_dir=test_skills_dir)

    yaml_path = Path("D:/done/app/logs/browser/dcf085dd/20260125_163729_楽天市場で「アベンヌウォーター」を検索して、検索結果を確認す.yaml")
    session = generator.load_session(yaml_path)

    skill = generator.from_session(session, skill_name="rakuten_search_test")

    # 保存
    saved_path = generator.save_skill(skill, overwrite=True)
    print(f"Saved to: {saved_path}")

    # 保存されたファイルを確認
    print("\nSaved files:")
    for f in saved_path.rglob("*"):
        if f.is_file():
            print(f"  {f.relative_to(saved_path)}")

    return saved_path


def test_convenience_function():
    """便利関数テスト"""
    print("\n=== 便利関数テスト ===")

    yaml_path = "D:/done/app/logs/browser/dcf085dd/20260125_163729_楽天市場で「アベンヌウォーター」を検索して、検索結果を確認す.yaml"

    try:
        # 重複回避のテスト用にスキル名を指定
        saved_path = generate_skill_from_yaml(yaml_path, skill_name="rakuten_search_generated")
        print(f"Generated skill at: {saved_path}")
    except FileExistsError as e:
        print(f"Skill already exists (expected): {e}")


if __name__ == "__main__":
    test_load_session()
    test_suggest_skill_name()
    test_generate_skill()
    test_save_skill()
    # test_convenience_function()  # 本番ディレクトリに書き込むのでコメントアウト

    print("\n=== All tests passed! ===")
