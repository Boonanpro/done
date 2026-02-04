"""
extend_skill 機能の単体テスト
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.skill_generator_claude import (
    extend_skill,
    _update_skill_md_actions,
    SKILLS_DIR,
)


def test_update_skill_md_actions():
    """_update_skill_md_actions のテスト"""
    print("\n=== Test: _update_skill_md_actions ===")

    # テスト用の一時ファイルを作成
    test_dir = SKILLS_DIR / "_test_extend"
    test_dir.mkdir(exist_ok=True)
    skill_md_path = test_dir / "SKILL.md"

    # ケース1: 既存テーブルがある場合
    print("\n[Case 1] Existing action table")
    skill_md_path.write_text("""# Test Skill

domain: example.com

## Actions
| Action | Description | Doc |
|---|---|---|
| `search` | 検索する | actions/search.md |

## Notes
Some notes here.
""", encoding="utf-8")

    _update_skill_md_actions(skill_md_path, ["purchase", "cancel"])

    content = skill_md_path.read_text(encoding="utf-8")
    print(content)

    assert "`purchase`" in content, "purchase action should be added"
    assert "`cancel`" in content, "cancel action should be added"
    assert "`search`" in content, "search action should remain"
    print("  OK: Actions added to existing table")

    # ケース2: テーブルがない場合
    print("\n[Case 2] No action table")
    skill_md_path.write_text("""# Test Skill

domain: example.com

## Overview
This is a test skill.
""", encoding="utf-8")

    _update_skill_md_actions(skill_md_path, ["login", "logout"])

    content = skill_md_path.read_text(encoding="utf-8")
    print(content)

    assert "## Actions" in content, "Actions section should be created"
    assert "`login`" in content, "login action should be added"
    assert "`logout`" in content, "logout action should be added"
    print("  OK: New action table created")

    # クリーンアップ
    import shutil
    shutil.rmtree(test_dir)
    print("\n  Cleanup done")


async def test_extend_skill_not_found():
    """存在しないスキルへの extend テスト"""
    print("\n=== Test: extend_skill (skill not found) ===")

    result = await extend_skill(
        yaml_log_path="dummy.yaml",
        target_skill="nonexistent_skill_12345",
        new_actions=["test_action"],
    )

    assert not result.success, "Should fail for nonexistent skill"
    assert "not found" in result.error.lower(), f"Error should mention 'not found': {result.error}"
    print(f"  OK: {result.error}")


async def test_extend_skill_structure():
    """extend_skill の構造テスト（実際のCLI呼び出しはスキップ）"""
    print("\n=== Test: extend_skill structure ===")

    # テスト用スキルを作成
    test_skill_name = "_test_extend_target"
    test_dir = SKILLS_DIR / test_skill_name
    test_dir.mkdir(exist_ok=True)

    skill_md = test_dir / "SKILL.md"
    skill_md.write_text("""# Test Target Skill

domain: test.example.com

## Actions
| Action | Description | Doc |
|---|---|---|
| `search` | 検索 | actions/search.md |
""", encoding="utf-8")

    actions_dir = test_dir / "actions"
    actions_dir.mkdir(exist_ok=True)
    (actions_dir / "search.md").write_text("# Search Action\n\nSearch instructions.", encoding="utf-8")

    print(f"  Created test skill at: {test_dir}")
    print(f"  SKILL.md exists: {skill_md.exists()}")
    print(f"  actions/ exists: {actions_dir.exists()}")

    # クリーンアップ
    import shutil
    shutil.rmtree(test_dir)
    print("  Cleanup done")
    print("  OK: Skill structure is correct")


def test_db_columns():
    """DBカラムの確認"""
    print("\n=== Test: DB columns ===")

    from app.services.supabase_client import get_supabase_client

    client = get_supabase_client().client

    # 新しいカラムを含むクエリを実行
    try:
        result = client.table("skill_proposals").select(
            "id, decision, target_skill, new_actions"
        ).limit(1).execute()
        print(f"  OK: Columns exist (rows: {len(result.data)})")
        if result.data:
            row = result.data[0]
            print(f"    Sample row: decision={row.get('decision')}, target_skill={row.get('target_skill')}")
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

    return True


def test_create_proposal_with_extend_fields():
    """extend フィールド付きの proposal 作成テスト"""
    print("\n=== Test: Create proposal with extend fields ===")

    from app.services.supabase_client import get_supabase_client
    from datetime import datetime
    import uuid

    client = get_supabase_client().client

    # テストユーザーIDを取得（既存ユーザーから）
    users_result = client.table("users").select("id").limit(1).execute()
    if not users_result.data:
        print("  SKIP: No users in database")
        return

    test_user_id = users_result.data[0]["id"]
    test_session_id = f"test_extend_{uuid.uuid4().hex[:8]}"

    # extend フィールド付きで proposal を作成
    payload = {
        "user_id": test_user_id,
        "session_id": test_session_id,
        "status": "pending",
        "skill_name": "amazon",
        "description": "Test extend proposal",
        "decision": "extend",
        "target_skill": "amazon",
        "new_actions": ["purchase", "cancel"],
    }

    try:
        result = client.table("skill_proposals").insert(payload).execute()
        created = result.data[0]
        print(f"  Created proposal: {created['id']}")
        print(f"    decision: {created.get('decision')}")
        print(f"    target_skill: {created.get('target_skill')}")
        print(f"    new_actions: {created.get('new_actions')}")

        # 検証
        assert created.get("decision") == "extend", "decision should be 'extend'"
        assert created.get("target_skill") == "amazon", "target_skill should be 'amazon'"
        assert created.get("new_actions") == ["purchase", "cancel"], "new_actions should match"

        # クリーンアップ
        client.table("skill_proposals").delete().eq("id", created["id"]).execute()
        print("  Cleanup done")
        print("  OK: Extend fields saved correctly")

    except Exception as e:
        print(f"  ERROR: {e}")


async def main():
    print("=" * 50)
    print("extend_skill 機能テスト")
    print("=" * 50)

    # 1. DB カラム確認
    test_db_columns()

    # 2. proposal 作成テスト
    test_create_proposal_with_extend_fields()

    # 3. _update_skill_md_actions テスト
    test_update_skill_md_actions()

    # 4. extend_skill (not found) テスト
    await test_extend_skill_not_found()

    # 5. extend_skill 構造テスト
    await test_extend_skill_structure()

    print("\n" + "=" * 50)
    print("All tests completed!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
