"""
マイグレーションを直接PostgreSQLに対して実行
psycopg2を使用してDDLを実行
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.config import settings


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_migration_direct.py <migration_number>")
        print("Example: python scripts/run_migration_direct.py 009")
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

    # psycopg2をインポート
    try:
        import psycopg2
    except ImportError:
        print("[ERROR] psycopg2 is not installed")
        print("Install it with: pip install psycopg2-binary")
        sys.exit(1)

    # Supabase接続文字列を構築
    # URLからホストを抽出
    supabase_url = settings.SUPABASE_URL
    # https://omcnusihkpfyvzglttop.supabase.co -> omcnusihkpfyvzglttop
    project_ref = supabase_url.split("//")[1].split(".")[0]

    # Supabase Postgres接続情報
    # Note: データベースパスワードが必要
    print("[WARN] Database password is required for direct connection")
    print("Get it from: Supabase Dashboard > Settings > Database > Database password")
    print()

    db_password = input("Enter database password: ").strip()

    if not db_password:
        print("[ERROR] Password is required")
        sys.exit(1)

    # 接続文字列（Direct connection）
    # IPv6アドレスを直接使用（[]で囲む必要がある）
    # Note: nslookupで取得したIPv6アドレス
    ipv6_addr = "2406:da18:243:7411:4345:d51c:4032:ea8f"
    host = f"[{ipv6_addr}]"

    # sslmodeを追加して接続を試行
    connection_string = f"postgresql://postgres:{db_password}@{host}:5432/postgres?sslmode=require"

    print(f"[INFO] Attempting connection to IPv6: {ipv6_addr} (with SSL)")

    print(f"[INFO] Connecting to database...")

    try:
        conn = psycopg2.connect(
            connection_string,
            connect_timeout=30,  # 30秒のタイムアウト
        )
        conn.autocommit = False
        cursor = conn.cursor()

        print("[SUCCESS] Connected successfully")
        print()

        # SQLを実行
        print("[INFO] Executing SQL...")
        cursor.execute(sql_content)

        # コミット
        conn.commit()

        print()
        print("=" * 80)
        print("[SUCCESS] Migration completed successfully!")
        print("=" * 80)
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
        print()

        cursor.close()
        conn.close()

    except psycopg2.Error as e:
        print(f"[ERROR] Database error: {e}")
        print()
        print("Please verify:")
        print("  - Database password is correct")
        print("  - Database is accessible")
        print("  - SQL syntax is valid")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
