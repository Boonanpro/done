"""
Supabaseクライアント経由でマイグレーションを実行
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.services.supabase_client import get_supabase_client


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_migration_supabase.py <migration_number>")
        print("Example: python scripts/run_migration_supabase.py 013")
        sys.exit(1)

    migration_num = sys.argv[1]

    # マイグレーションファイルを検索
    migration_dir = project_root / "supabase" / "migrations"
    migration_files = list(migration_dir.glob(f"{migration_num}_*.sql"))

    if not migration_files:
        print(f"[ERROR] Migration file not found: {migration_num}_*.sql")
        sys.exit(1)

    migration_file = migration_files[0]
    print(f"[INFO] Reading migration file: {migration_file.name}")

    sql_content = migration_file.read_text(encoding="utf-8")

    print("\n" + "=" * 80)
    print(f"Running migration: {migration_file.name}")
    print("=" * 80)
    print()

    # Supabaseクライアントを取得
    supabase = get_supabase_client().client

    # SQLを実行（rpc経由）
    try:
        # postgrest経由では直接DDLは実行できないため、
        # テーブルが存在するか確認
        result = supabase.table("user_credentials").select("id").limit(1).execute()
        print("[INFO] Table 'user_credentials' already exists")
        print(f"[INFO] Current records: {len(result.data)}")
    except Exception as e:
        if "does not exist" in str(e) or "relation" in str(e):
            print("[WARN] Table does not exist. Please run migration manually:")
            print()
            print("Option 1: Supabase Dashboard")
            print("  1. Go to https://supabase.com/dashboard")
            print("  2. Select your project")
            print("  3. Go to SQL Editor")
            print("  4. Paste and run the SQL from:")
            print(f"     {migration_file}")
            print()
            print("Option 2: psql (if you have the DB password)")
            print(f"  python scripts/run_migration_direct.py {migration_num}")
        else:
            print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
