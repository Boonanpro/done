"""
マイグレーションを実行するスクリプト
Service Role Keyを使ってSQLを直接実行
"""
import asyncio
import sys
from pathlib import Path
from supabase import create_client

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.config import settings


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_migration.py <migration_number>")
        print("Example: python scripts/run_migration.py 009")
        sys.exit(1)

    migration_num = sys.argv[1]

    # マイグレーションファイルを検索
    migration_dir = project_root / "supabase" / "migrations"
    migration_files = list(migration_dir.glob(f"{migration_num}_*.sql"))

    if not migration_files:
        print(f"❌ Migration file not found: {migration_num}_*.sql")
        sys.exit(1)

    migration_file = migration_files[0]
    print(f"📄 Reading migration file: {migration_file.name}")

    sql_content = migration_file.read_text(encoding="utf-8")

    # Service Role Keyでクライアントを作成
    if not settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_SERVICE_ROLE_KEY == "your-supabase-service-role-key":
        print("❌ SUPABASE_SERVICE_ROLE_KEY is not set in .env file")
        sys.exit(1)

    print(f"🔌 Connecting to Supabase: {settings.SUPABASE_URL}")
    supabase = create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_ROLE_KEY,
    )

    print("\n" + "=" * 80)
    print(f"Running migration: {migration_file.name}")
    print("=" * 80)
    print()

    # SQLを個別の文に分割して実行
    statements = []
    current_statement = []
    in_function = False

    for line in sql_content.split("\n"):
        # コメント行のみの場合はスキップ
        stripped = line.strip()
        if stripped.startswith("--") and not current_statement:
            continue

        current_statement.append(line)

        # FUNCTION/TRIGGER定義の中かチェック
        if "CREATE" in line.upper() and ("FUNCTION" in line.upper() or "TRIGGER" in line.upper()):
            in_function = True

        # セミコロンで終わる場合
        if stripped.endswith(";"):
            # FUNCTION定義の終了を検出
            if in_function and ("END;" in stripped.upper() or "LANGUAGE" in line.upper()):
                in_function = False

            if not in_function:
                statement = "\n".join(current_statement).strip()
                if statement and not statement.startswith("--"):
                    statements.append(statement)
                current_statement = []

    # 残りの文があれば追加
    if current_statement:
        statement = "\n".join(current_statement).strip()
        if statement and not statement.startswith("--"):
            statements.append(statement)

    print(f"📊 Found {len(statements)} SQL statements to execute")
    print()

    success_count = 0
    error_count = 0
    errors = []

    for i, statement in enumerate(statements, 1):
        # 最初の行を表示（説明用）
        first_line = statement.split("\n")[0].strip()
        if len(first_line) > 70:
            first_line = first_line[:70] + "..."

        print(f"[{i}/{len(statements)}] {first_line}")

        try:
            # PostgreRESTを通してSQLを実行
            # Supabaseはrpc経由でSQLを実行できないので、各テーブル操作に分解する必要がある
            # ただし、CREATE TABLE等のDDLはREST APIでは実行できない

            # 代替案: postgrest-pyやpsycopg2を使う
            # ここではpostgrest経由で実行できないため、エラーを報告
            print(f"  ⚠️  Cannot execute DDL via REST API")
            print(f"  ℹ️  Please run this migration via Supabase Dashboard SQL Editor")
            error_count += 1

        except Exception as e:
            print(f"  ❌ Error: {e}")
            errors.append((i, statement, str(e)))
            error_count += 1

    print()
    print("=" * 80)
    print(f"Results: {success_count} succeeded, {error_count} failed/skipped")
    print("=" * 80)
    print()

    if error_count > 0:
        print("⚠️  Note: Supabase client cannot execute DDL statements (CREATE TABLE, etc.)")
        print("Please use one of the following methods:")
        print()
        print("Method 1: Supabase Dashboard (Recommended)")
        print("  1. Go to https://app.supabase.com")
        print("  2. Select your project")
        print("  3. Go to SQL Editor")
        print("  4. Create new query")
        print(f"  5. Paste the contents of {migration_file.name}")
        print("  6. Click Run")
        print()
        print("Method 2: psql command")
        print(f"  psql <connection_string> -f {migration_file}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
