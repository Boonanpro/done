"""ダンが「追跡付き」でメール送信するための CLI。

返信を email_poller が照合できるよう、送信時に external_message_routes へ記録する。
room_id / user_id は既定で環境変数 DAN_ROOM_ID / DAN_USER_ID から取る（cli_runner が
ダンプロセスに渡している）。Bash ツールから直接呼べる。

使い方:
  python D:/done/scripts/dan_send_email.py \
    --to "client@example.com" --subject "ご提案の件" --body "本文..."

  # 本文をファイルから（長文・改行を安全に渡す）
  python D:/done/scripts/dan_send_email.py --to x --subject y --body-file /tmp/body.txt
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.email_send import send_tracked_email


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True, help="宛先メールアドレス")
    ap.add_argument("--subject", required=True, help="件名")
    ap.add_argument("--body", help="本文（--body-file と排他）")
    ap.add_argument("--body-file", help="本文を読むファイルパス")
    ap.add_argument("--from-name", default="Done", help="差出人表示名")
    ap.add_argument("--room", default=os.getenv("DAN_ROOM_ID"), help="紐づけるルームID（既定: $DAN_ROOM_ID）")
    ap.add_argument("--user", default=os.getenv("DAN_USER_ID"), help="ユーザーID（既定: $DAN_USER_ID）")
    args = ap.parse_args()

    body = args.body
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    if not body:
        print(json.dumps({"sent": False, "error": "--body または --body-file が必要"}, ensure_ascii=False))
        sys.exit(1)

    # room/user が無い場合は owner にフォールバック（room は record_outbound に必須）
    user_id = args.user
    room_id = args.room
    if not user_id:
        from app.services.owner import resolve_owner_user_id
        user_id = resolve_owner_user_id()
    if not room_id:
        print(json.dumps({
            "sent": False,
            "error": "room_id 不明（$DAN_ROOM_ID 無し）。--room を指定してください。返信照合に必要です。",
        }, ensure_ascii=False))
        sys.exit(1)

    try:
        result = send_tracked_email(
            to=args.to, subject=args.subject, body=body,
            user_id=user_id, origin_room_id=room_id, from_name=args.from_name,
        )
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"sent": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
