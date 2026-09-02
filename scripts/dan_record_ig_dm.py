# -*- coding: utf-8 -*-
"""インスタDMを送ったことを台帳に記録する（返信を検知するために必須）。

ダンがブラウザでDMを送った直後にこれを実行する。記録が無いと、
instagram_poller はそのアカウントを巡回しないし、返信が来ても
「どのルームの件か」が分からず通知タブ止まりになる。

使い方:
    python scripts/dan_record_ig_dm.py --account instagram_styleup --to someone \
        [--room <room_id>] [--user <user_id>] [--note "見積の打診"]

    --room 省略時は環境変数 DAN_ROOM_ID、--user 省略時は DAN_USER_ID を使う。
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True,
                        help="送信に使ったインスタアカウント（例: instagram_styleup）")
    parser.add_argument("--to", required=True, help="相手のユーザーネーム（@ は付けても付けなくても可）")
    parser.add_argument("--room", default=os.getenv("DAN_ROOM_ID"))
    parser.add_argument("--user", default=os.getenv("DAN_USER_ID"))
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    if not args.room:
        print("ERROR: --room か DAN_ROOM_ID が必要（どのルームの用件かが台帳の要）")
        return 2

    user_id = args.user
    if not user_id:
        from app.services.owner import resolve_owner_user_id
        user_id = resolve_owner_user_id()
    if not user_id:
        print("ERROR: user_id が解決できない")
        return 2

    handle = args.to.lstrip("@").strip().lower()

    from app.services.external_message_routing import get_external_message_routing_service
    svc = get_external_message_routing_service()
    route = await svc.record_outbound(
        user_id=user_id,
        channel="instagram",
        origin_room_id=args.room,
        external_account_id=args.account,
        external_recipient_id=handle,
        metadata={"note": args.note} if args.note else {},
    )
    print(f"記録しました: {args.account} → @{handle} (room={args.room[:8]}) route={route['id'][:8]}")
    print("これで返信が来たら、このルームでダンが起動します。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
