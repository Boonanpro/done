"""
Issue Tracker マイグレーション実行スクリプト
009_issue_tracker.sql を直接実行する
"""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.core.supabase_client import get_supabase_client


async def main():
    # マイグレーションファイルを読み込み
    migration_file = project_root / "supabase" / "migrations" / "009_issue_tracker.sql"

    if not migration_file.exists():
        print(f"❌ Migration file not found: {migration_file}")
        sys.exit(1)

    print(f"Reading migration file: {migration_file}")
    sql_content = migration_file.read_text(encoding="utf-8")

    # Supabaseクライアントを取得
    supabase = get_supabase_client()

    print("\n" + "=" * 80)
    print("Running migration: 009_issue_tracker.sql")
    print("=" * 80)
    print()

    try:
        # SQLを実行
        result = supabase.rpc("exec_sql", {"sql": sql_content}).execute()

        print("✅ Migration executed successfully!")
        print()
        print("Created tables:")
        print("  - issues")
        print("  - issue_occurrences")
        print()
        print("Created view:")
        print("  - open_issues_by_priority")
        print()
        print("You can now use the issue tracker:")
        print("  python scripts/list_issues.py")
        print("  python scripts/show_issue.py <issue_id>")
        print("  python scripts/resolve_issue.py <issue_id>")

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        print()
        print("Trying alternative method: executing SQL statements individually...")

        # 個別のSQL文に分割して実行を試みる
        await execute_sql_individually(sql_content)


async def execute_sql_individually(sql_content: str):
    """
    SQLを個別の文に分割して実行する（フォールバック）
    """
    from app.core.supabase_client import get_supabase_admin_client

    supabase = get_supabase_admin_client()

    # SQL文を分割（簡易的な方法）
    statements = []
    current = []

    for line in sql_content.split("\n"):
        # コメント行をスキップ
        if line.strip().startswith("--"):
            continue

        current.append(line)

        # セミコロンで終わる場合は1つの文として扱う
        if line.strip().endswith(";"):
            statement = "\n".join(current).strip()
            if statement:
                statements.append(statement)
            current = []

    print(f"Found {len(statements)} SQL statements")
    print()

    success_count = 0
    error_count = 0

    for i, statement in enumerate(statements, 1):
        # 短い説明を表示
        first_line = statement.split("\n")[0][:60]
        print(f"[{i}/{len(statements)}] Executing: {first_line}...")

        try:
            # PostgRESTを使ってSQLを実行
            # Note: これは通常のSupabaseクライアントでは直接実行できない
            # Database APIやpg-adminを使う必要がある
            print(f"  ⚠️  Skipped (need admin access)")
            error_count += 1
        except Exception as e:
            print(f"  ❌ Error: {e}")
            error_count += 1

    print()
    print("=" * 80)
    print(f"Results: {success_count} succeeded, {error_count} failed/skipped")
    print("=" * 80)
    print()
    print("⚠️  Note: Direct SQL execution requires database admin access.")
    print("Please run the migration via Supabase Dashboard:")
    print()
    print("1. Go to https://app.supabase.com")
    print("2. Select your project")
    print("3. Go to SQL Editor")
    print("4. Paste the contents of supabase/migrations/009_issue_tracker.sql")
    print("5. Click Run")


if __name__ == "__main__":
    asyncio.run(main())
