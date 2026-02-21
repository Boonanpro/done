"""
プロジェクトのクリーンアップスクリプト

指定キーワードに一致するプロジェクトを検索し、
関連するチャットルーム・メッセージも含めて完全削除する。

使い方:
  python scripts/cleanup_project.py              # 全プロジェクト一覧表示
  python scripts/cleanup_project.py "ポルノ"      # キーワードで検索して削除
  python scripts/cleanup_project.py --all         # 全プロジェクト削除
"""
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from supabase import create_client


def get_client():
    key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY
    return create_client(settings.SUPABASE_URL, key)


def list_projects(client):
    result = client.table("projects").select("id, title, status, room_id, created_at").order("created_at", desc=True).execute()
    return result.data or []


def delete_project_fully(client, project):
    """プロジェクトと関連チャットルームを完全削除"""
    project_id = project["id"]
    room_id = project.get("room_id")
    title = project["title"]

    print(f"\n  削除中: {title} ({project_id})")

    # 1. プロジェクト削除（project_proposals, execution_events は CASCADE）
    client.table("projects").delete().eq("id", project_id).execute()
    print(f"    ✓ プロジェクト削除")

    # 2. チャットルームも削除（メッセージ、メンバーは CASCADE）
    if room_id:
        try:
            client.table("chat_messages").delete().eq("room_id", room_id).execute()
            print(f"    ✓ チャットメッセージ削除")
        except Exception as e:
            print(f"    △ メッセージ削除スキップ: {e}")

        try:
            client.table("chat_room_members").delete().eq("room_id", room_id).execute()
            print(f"    ✓ ルームメンバー削除")
        except Exception as e:
            print(f"    △ メンバー削除スキップ: {e}")

        try:
            client.table("chat_rooms").delete().eq("id", room_id).execute()
            print(f"    ✓ チャットルーム削除")
        except Exception as e:
            print(f"    △ ルーム削除スキップ: {e}")

    print(f"  ✓ 完了: {title}")


def main():
    client = get_client()
    projects = list_projects(client)

    if not projects:
        print("プロジェクトが見つかりません。")
        return

    # 引数なし: 一覧表示のみ
    if len(sys.argv) < 2:
        print(f"\n=== プロジェクト一覧 ({len(projects)}件) ===\n")
        for i, p in enumerate(projects, 1):
            print(f"  {i}. [{p['status']}] {p['title']}")
            print(f"     ID: {p['id']}")
            print(f"     作成: {p['created_at']}")
        print(f"\n削除するには: python scripts/cleanup_project.py \"検索キーワード\"")
        return

    # --all: 全削除
    if sys.argv[1] == "--all":
        targets = projects
    else:
        # キーワード検索
        keyword = sys.argv[1]
        targets = [p for p in projects if keyword in (p["title"] or "")]

    if not targets:
        print(f"キーワード '{sys.argv[1]}' に一致するプロジェクトはありません。")
        return

    print(f"\n=== 削除対象 ({len(targets)}件) ===")
    for p in targets:
        print(f"  - [{p['status']}] {p['title']}")

    confirm = input(f"\nこれら {len(targets)} 件を完全削除しますか？ (y/N): ")
    if confirm.lower() != "y":
        print("キャンセルしました。")
        return

    for p in targets:
        delete_project_fully(client, p)

    print(f"\n=== 削除完了 ({len(targets)}件) ===")


if __name__ == "__main__":
    main()
