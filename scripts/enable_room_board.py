# -*- coding: utf-8 -*-
"""部屋ボードの有効化/無効化スクリプト（1部屋テスト用）。

使い方:
  python scripts/enable_room_board.py --title 認証        # タイトル部分一致で有効化
  python scripts/enable_room_board.py --project-id <id>
  python scripts/enable_room_board.py --title 認証 --digest  # 有効化して初回消化まで実行
  python scripts/enable_room_board.py --title 認証 --off     # 無効化
  python scripts/enable_room_board.py --list                # 有効な部屋の一覧
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", help="プロジェクトタイトルの部分一致")
    ap.add_argument("--project-id", help="プロジェクトID直接指定")
    ap.add_argument("--off", action="store_true", help="無効化する")
    ap.add_argument("--digest", action="store_true", help="有効化後に初回消化を実行")
    ap.add_argument("--force", action="store_true", help="消化時にカーソル無視で全履歴から再消化")
    ap.add_argument("--list", action="store_true", help="board_enabled な部屋を一覧")
    ap.add_argument("--create-title", help="この名前でボード部屋を新規作成して有効化")
    ap.add_argument("--seed-from", help="このプロジェクト(ID)の部屋履歴からボードを種付けする")
    args = ap.parse_args()

    from app.services.room_board_service import (
        digest_project,
        get_project_with_board,
        list_board_projects,
        set_board_enabled,
        _sb,
    )

    if args.create_title:
        import asyncio
        from app.services.project_service import ProjectService
        seed_row = get_project_with_board(project_id=args.seed_from) if args.seed_from else None
        if args.seed_from and not seed_row:
            print("--seed-from のプロジェクトが見つかりません")
            return 1
        # user_id は種元 or 既存プロジェクトの先頭から引き継ぐ
        if seed_row:
            user_id = _sb().table("projects").select("user_id").eq("id", seed_row["id"]).limit(1).execute().data[0]["user_id"]
        else:
            user_id = _sb().table("projects").select("user_id").limit(1).execute().data[0]["user_id"]
        service = ProjectService()
        project = asyncio.run(service.create_project(user_id=user_id, title=args.create_title))
        project_id = project["id"] if isinstance(project, dict) else project.id
        set_board_enabled(project_id, True)
        row = get_project_with_board(project_id=project_id)
        print(f"作成+有効化: {args.create_title} (project={project_id}, room={row['room_id']})")
        if seed_row:
            from app.services.room_board_service import seed_from_history
            result = seed_from_history(row, seed_row["room_id"])
            print(f"種付け消化: digested={result['digested']} reason={result['reason']} chunks={result.get('chunks')}")
            if result.get("board"):
                print(json.dumps(result["board"], ensure_ascii=False, indent=1))
        return 0

    if args.list:
        for p in list_board_projects():
            board = (p.get("metadata") or {}).get("board") or {}
            print(f"- {p['title']} (project={p['id']}, room={p['room_id']}, v{board.get('version', 0)})")
        return 0

    project = None
    if args.project_id:
        project = get_project_with_board(project_id=args.project_id)
    elif args.title:
        res = (
            _sb().table("projects")
            .select("id, room_id, title, metadata")
            .ilike("title", f"%{args.title}%")
            .execute()
        )
        rows = res.data or []
        if len(rows) > 1:
            print("複数ヒットしました。--project-id で指定してください:")
            for r in rows:
                print(f"- {r['title']} (project={r['id']}, room={r['room_id']})")
            return 1
        project = rows[0] if rows else None
    else:
        ap.print_help()
        return 1

    if not project:
        print("プロジェクトが見つかりません")
        return 1

    set_board_enabled(project["id"], not args.off)
    state = "無効化" if args.off else "有効化"
    print(f"{state}しました: {project['title']} (project={project['id']}, room={project['room_id']})")

    if args.seed_from and not args.off:
        from app.services.room_board_service import seed_from_history
        seed_row = get_project_with_board(project_id=args.seed_from)
        if not seed_row:
            print("--seed-from のプロジェクトが見つかりません")
            return 1
        project = get_project_with_board(project_id=project["id"])  # metadata再取得
        result = seed_from_history(project, seed_row["room_id"])
        print(f"種付け消化: digested={result['digested']} reason={result['reason']} chunks={result.get('chunks')}")
        if result.get("board"):
            print(json.dumps(result["board"], ensure_ascii=False, indent=1))
        return 0

    if args.digest and not args.off:
        project = get_project_with_board(project_id=project["id"])  # metadata再取得
        result = digest_project(project, force=args.force)
        print(f"消化結果: digested={result['digested']} reason={result['reason']}")
        if result.get("board"):
            print(json.dumps(result["board"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
