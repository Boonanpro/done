"""
マイグレーション014をSupabaseに適用するスクリプト
"""
import asyncio
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.supabase_client import get_supabase_client


MIGRATION_SQL = """
-- Issue Tracker v2: スキル化のためのイシュー拡張
-- screenshots, html_snapshot, page_url, fallback_action を追加

-- issues テーブルに新カラム追加
ALTER TABLE issues ADD COLUMN IF NOT EXISTS screenshots JSONB DEFAULT '[]';
ALTER TABLE issues ADD COLUMN IF NOT EXISTS html_snapshot_path TEXT;
ALTER TABLE issues ADD COLUMN IF NOT EXISTS page_url TEXT;
ALTER TABLE issues ADD COLUMN IF NOT EXISTS fallback_action TEXT;

-- issue_occurrences テーブルにも同じカラム追加（各発生時の状態を記録）
ALTER TABLE issue_occurrences ADD COLUMN IF NOT EXISTS screenshots JSONB DEFAULT '[]';
ALTER TABLE issue_occurrences ADD COLUMN IF NOT EXISTS html_snapshot_path TEXT;
ALTER TABLE issue_occurrences ADD COLUMN IF NOT EXISTS page_url TEXT;
"""


def apply_migration():
    """マイグレーションを適用"""
    print("Connecting to Supabase...")
    wrapper = get_supabase_client()
    client = wrapper.client

    print("Applying migration 014_issue_tracker_v2...")

    # 個別にALTER TABLEを実行（Supabaseは複数文を一度に実行できない場合がある）
    statements = [
        "ALTER TABLE issues ADD COLUMN IF NOT EXISTS screenshots JSONB DEFAULT '[]'",
        "ALTER TABLE issues ADD COLUMN IF NOT EXISTS html_snapshot_path TEXT",
        "ALTER TABLE issues ADD COLUMN IF NOT EXISTS page_url TEXT",
        "ALTER TABLE issues ADD COLUMN IF NOT EXISTS fallback_action TEXT",
        "ALTER TABLE issue_occurrences ADD COLUMN IF NOT EXISTS screenshots JSONB DEFAULT '[]'",
        "ALTER TABLE issue_occurrences ADD COLUMN IF NOT EXISTS html_snapshot_path TEXT",
        "ALTER TABLE issue_occurrences ADD COLUMN IF NOT EXISTS page_url TEXT",
    ]

    for stmt in statements:
        try:
            # RPC経由でSQLを実行
            result = client.rpc('exec_sql', {'sql': stmt}).execute()
            print(f"  OK: {stmt[:50]}...")
        except Exception as e:
            # カラムが既に存在する場合などはエラーになることがある
            error_msg = str(e)
            if "already exists" in error_msg.lower() or "duplicate" in error_msg.lower():
                print(f"  SKIP (already exists): {stmt[:50]}...")
            else:
                print(f"  ERROR: {stmt[:50]}...")
                print(f"    {e}")

    print("\nMigration complete!")

    # カラムが追加されたか確認
    print("\nVerifying columns...")
    try:
        result = client.table("issues").select("id, screenshots, html_snapshot_path, page_url, fallback_action").limit(1).execute()
        print("  issues table: OK (new columns exist)")
    except Exception as e:
        print(f"  issues table: ERROR - {e}")

    try:
        result = client.table("issue_occurrences").select("id, screenshots, html_snapshot_path, page_url").limit(1).execute()
        print("  issue_occurrences table: OK (new columns exist)")
    except Exception as e:
        print(f"  issue_occurrences table: ERROR - {e}")


if __name__ == "__main__":
    apply_migration()
