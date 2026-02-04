"""
マイグレーション017をSupabaseに適用するスクリプト
- learning_events テーブル
- learned_rules テーブル
- event_links テーブル

注意: このスクリプトはSupabaseダッシュボードの SQL Editor で
      直接 017_learning_system.sql を実行した方が確実です。
"""
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))


def print_instructions():
    """手動適用の手順を表示"""
    migration_file = Path(__file__).parent.parent / "supabase" / "migrations" / "017_learning_system.sql"

    print("=" * 60)
    print("マイグレーション 017_learning_system.sql の適用手順")
    print("=" * 60)
    print()
    print("Supabaseダッシュボードで以下の手順を実行してください:")
    print()
    print("1. Supabase Dashboard にログイン")
    print("   https://app.supabase.com/")
    print()
    print("2. プロジェクトを選択")
    print()
    print("3. 左メニューから 'SQL Editor' を選択")
    print()
    print("4. 以下のファイルの内容をコピー&ペースト:")
    print(f"   {migration_file}")
    print()
    print("5. 'Run' ボタンをクリック")
    print()
    print("=" * 60)
    print()

    if migration_file.exists():
        print("SQLファイルの内容（参考）:")
        print("-" * 40)
        with open(migration_file, "r", encoding="utf-8") as f:
            content = f.read()
            # 最初の50行だけ表示
            lines = content.split("\n")[:50]
            print("\n".join(lines))
            if len(content.split("\n")) > 50:
                print("... (続きはファイルを参照)")
        print("-" * 40)


def verify_tables():
    """テーブルが存在するか確認"""
    from app.services.supabase_client import get_supabase_client

    print("\nテーブル存在確認...")
    wrapper = get_supabase_client()
    client = wrapper.client

    tables = ["learning_events", "learned_rules", "event_links"]

    for table in tables:
        try:
            result = client.table(table).select("id").limit(1).execute()
            print(f"  ✅ {table}: 存在します")
        except Exception as e:
            error_msg = str(e)
            if "could not find" in error_msg.lower() or "PGRST205" in error_msg:
                print(f"  ❌ {table}: 存在しません（マイグレーション未適用）")
            else:
                print(f"  ⚠️ {table}: エラー - {e}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="マイグレーション017の適用")
    parser.add_argument("--verify", action="store_true", help="テーブル存在確認のみ")
    args = parser.parse_args()

    if args.verify:
        verify_tables()
    else:
        print_instructions()
        verify_tables()
