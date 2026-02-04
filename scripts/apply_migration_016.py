"""
マイグレーション016をSupabaseに適用するスクリプト
- skill_proposals に decision, target_skill, new_actions カラムを追加
"""
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.supabase_client import get_supabase_client


def apply_migration():
    """マイグレーションを適用"""
    print("Connecting to Supabase...")
    wrapper = get_supabase_client()
    client = wrapper.client

    print("Applying migration 016_skill_proposals_extend...")

    # 個別にALTER TABLEを実行
    statements = [
        "ALTER TABLE skill_proposals ADD COLUMN IF NOT EXISTS decision TEXT",
        "ALTER TABLE skill_proposals ADD COLUMN IF NOT EXISTS target_skill TEXT",
        "ALTER TABLE skill_proposals ADD COLUMN IF NOT EXISTS new_actions JSONB DEFAULT '[]'",
    ]

    for stmt in statements:
        try:
            result = client.rpc('exec_sql', {'sql': stmt}).execute()
            print(f"  OK: {stmt}")
        except Exception as e:
            error_msg = str(e)
            if "already exists" in error_msg.lower() or "duplicate" in error_msg.lower():
                print(f"  SKIP (already exists): {stmt}")
            else:
                print(f"  ERROR: {stmt}")
                print(f"    {e}")

    print("\nMigration complete!")

    # カラムが追加されたか確認
    print("\nVerifying columns...")
    try:
        result = client.table("skill_proposals").select("id, decision, target_skill, new_actions").limit(1).execute()
        print("  skill_proposals table: OK (new columns exist)")
    except Exception as e:
        print(f"  skill_proposals table: ERROR - {e}")


if __name__ == "__main__":
    apply_migration()
