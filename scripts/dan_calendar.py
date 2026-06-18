"""ダンがGoogleカレンダーを操作するCLI（予定一覧・空き時間・予定作成）。

接続済みのGoogleカレンダー(calendar_connections, shub6923)に対して操作する。
user_id は既定で $DAN_USER_ID（無ければ owner）。Bash ツールから直接呼べる。

使い方:
  python D:/done/scripts/dan_calendar.py list --days 7
  python D:/done/scripts/dan_calendar.py free --days 5
  python D:/done/scripts/dan_calendar.py add --title "本田様 打ち合わせ(Zoom)" \
    --start "2026-06-20T15:00:00" --end "2026-06-20T16:00:00" \
    --description "ホームページ制作の件"
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.calendar_service import get_calendar_service


def _uid(args):
    uid = args.user or os.getenv("DAN_USER_ID")
    if not uid:
        from app.services.owner import resolve_owner_user_id
        uid = resolve_owner_user_id()
    return uid


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="今後N日の予定")
    p_list.add_argument("--days", type=int, default=7)
    p_list.add_argument("--user", default=None)

    p_free = sub.add_parser("free", help="今後N日の空き時間(9-18時)")
    p_free.add_argument("--days", type=int, default=7)
    p_free.add_argument("--user", default=None)

    p_add = sub.add_parser("add", help="予定を作成")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--start", required=True, help="ISO8601(例 2026-06-20T15:00:00) or 日付のみ(終日)")
    p_add.add_argument("--end", required=True)
    p_add.add_argument("--description", default="")
    p_add.add_argument("--location", default="")
    p_add.add_argument("--user", default=None)

    args = ap.parse_args()
    svc = get_calendar_service()
    uid = _uid(args)

    try:
        if args.cmd == "list":
            print(json.dumps(svc.get_events(uid, days=args.days), ensure_ascii=False))
        elif args.cmd == "free":
            print(json.dumps(svc.find_free_slots(uid, days=args.days), ensure_ascii=False))
        elif args.cmd == "add":
            r = svc.create_event(uid, title=args.title, start=args.start, end=args.end,
                                 description=args.description, location=args.location)
            print(json.dumps(r, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
