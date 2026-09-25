"""ダンがカレンダーを操作するCLI。つながっている全アカウント（Google など、複数可）が対象。

読むときは全アカウントの予定を、どのアカウント・どのカレンダーかを添えて返す。書くときは --account で選んだアカウント
（アドレスの一部で可。例: 0aw）、無ければ既定のアカウントに入れる。予定の変更（メモの追記・時刻・通知）と削除もできる。
user_id は既定で $DAN_USER_ID（無ければ owner）。Bash ツールから直接呼べる。

使い方:
  python D:/done/scripts/dan_calendar.py accounts
  python D:/done/scripts/dan_calendar.py list --days 7 [--account 0aw]
  python D:/done/scripts/dan_calendar.py free --days 5
  python D:/done/scripts/dan_calendar.py add --title "本田様 打ち合わせ(Zoom)" --start "2026-06-20T15:00:00" \
    --end "2026-06-20T16:00:00" [--description "..."] [--location "..."] [--reminders 10 60] [--account 0aw]
  python D:/done/scripts/dan_calendar.py update --id <予定id> [--description "..."] [--title ...] [--start ...] [--end ...]
    [--location ...] [--reminders 10]      （id は list の結果の id。アカウントとカレンダーは自動で探す）
  python D:/done/scripts/dan_calendar.py delete --id <予定id>
  python D:/done/scripts/dan_calendar.py default --account 0aw      （新しい予定の既定の書き込み先を変える）
  python D:/done/scripts/dan_calendar.py connect --account 0aw325171@gmail.com [--provider google] [--replace shub]
    （そのアカウントをつなぐための URL を出す。ダンがブラウザで開き、そのアカウントでログインして許可まで進める）
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services import connected_accounts
from app.services.calendar_service import CAPABILITY, get_calendar_service


def _uid(args):
    uid = args.user or os.getenv("DAN_USER_ID")
    if not uid:
        from app.services.owner import resolve_owner_user_id
        uid = resolve_owner_user_id()
    return uid


def _reconnect(svc, uid, failed):
    """A reconnect link per expired account: open it, sign in as that account, agree; then run the command again."""
    links = []
    for f in failed:
        row = next((a for a in connected_accounts.list_accounts(uid, CAPABILITY) if a["account"] == f["account"]), None)
        if row:
            links.append({"account": row["account"], "reconnect_url": svc.get_auth_url(uid, row["provider"], replace_id=row["id"], hint=row["account"])})
    return links


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, help_ in (("accounts", "つながっているカレンダーのアカウント"), ("list", "今日からN日の予定"), ("free", "今後N日の空き時間(9-18時)"),
                        ("add", "予定を作成"), ("update", "予定を変える"), ("delete", "予定を消す"), ("default", "既定の書き込み先を変える"),
                        ("connect", "アカウントをつなぐURL（開いてログインし許可する）")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--user", default=None)
        p.add_argument("--account", default=None, help="アカウント（アドレスの一部で可）。無ければ list は全部、書き込みは既定")
        if name in ("list", "free"):
            p.add_argument("--days", type=int, default=7)
        if name == "list":
            p.add_argument("--from", dest="start", default=None, help="この日から（YYYY-MM-DD、過去も可）。省略時は今日")
        if name in ("add", "update"):
            p.add_argument("--title", required=(name == "add"))
            p.add_argument("--start", required=(name == "add"), help="ISO8601(例 2026-06-20T15:00:00) or 日付のみ(終日)")
            p.add_argument("--end", required=(name == "add"))
            p.add_argument("--description", default=None, help="メモ（update では置き換え。追記は今のメモ＋追記で渡す）")
            p.add_argument("--location", default=None)
            p.add_argument("--reminders", type=int, nargs="*", default=None, help="通知（何分前、複数可）")
        if name == "connect":
            p.add_argument("--provider", default="google")
            p.add_argument("--replace", default=None, help="このアカウントと入れ替える（アドレスの一部で可）")
        if name in ("update", "delete"):
            p.add_argument("--id", required=True)
            p.add_argument("--calendar", default=None)

    args = ap.parse_args()
    svc = get_calendar_service()
    uid = _uid(args)
    try:
        if args.cmd == "accounts":
            out = asyncio.run(svc.get_status(uid))
        elif args.cmd == "list":
            got = svc.get_events_with_source(uid, days=args.days, max_results=50, account=args.account, start_date=args.start)
            out = {"events": got["events"], "source": got["source"]}
            if got["source"] and got["source"].get("failed"):
                out["reconnect"] = _reconnect(svc, uid, got["source"]["failed"])
        elif args.cmd == "free":
            out = svc.find_free_slots(uid, days=args.days)
        elif args.cmd == "add":
            out = svc.create_event(uid, title=args.title, start=args.start, end=args.end, description=args.description or "",
                                   location=args.location or "", account=args.account, reminders=args.reminders)
        elif args.cmd == "update":
            fields = {k: getattr(args, k) for k in ("title", "start", "end", "description", "location", "reminders") if getattr(args, k) is not None}
            out = svc.update_event(uid, args.id, account=args.account, calendar_id=args.calendar, **fields)
        elif args.cmd == "delete":
            out = svc.delete_event(uid, args.id, account=args.account, calendar_id=args.calendar)
        elif args.cmd == "default":
            row = connected_accounts.find(uid, CAPABILITY, args.account)
            out = {"default": row["account"]} if row and svc.set_default(uid, row["id"]) else {"error": "そのアカウントはありません"}
        elif args.cmd == "connect":
            replace = connected_accounts.find(uid, CAPABILITY, args.replace) if args.replace else None
            if args.replace and not replace:
                out = {"error": f"入れ替え元「{args.replace}」はつながっていません"}
            else:
                out = {"auth_url": svc.get_auth_url(uid, args.provider, replace_id=replace["id"] if replace else None, hint=args.account),
                       "next": ("この URL をブラウザで開き、" + (args.account or "つなぐアカウント") + " を選ぶ（または入力する）。ログインは保存済みの情報"
                                "（get_credentials の id が一致するもの。パスワードは fill_credential、2段階認証は fill_totp_code）で行う。"
                                "許可の画面では、カレンダーの権限にチェックを入れて「続行」「許可」まで進める。"
                                "「カレンダーを連携しました」の画面が出たら終わり。最後に accounts で並んでいるか確かめる。"
                                "ログインで Google に確認画面（自動操作の疑いなど）が出たら、やり直しを繰り返さずに止めて報告する。")}
        print(json.dumps(out, ensure_ascii=False))
        if isinstance(out, dict) and out.get("error"):
            sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": str(e)[:300]}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
