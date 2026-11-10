"""作業中に届いた知らせの受け口（app/services/room_receiver.py）から、作業中のダンへ「作業の前提が変わった」と伝える。

使い方: echo "何が変わったか" | python scripts/tell_room_work.py --room <room_id>
部屋の会話を持っている本体（release core）の内部入口へ渡す。作業中でなければ何もしない。
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--room', required=True)
    args = ap.parse_args()
    text = sys.stdin.read().strip()
    if not text:
        print('伝える本文を標準入力で渡してください', file=sys.stderr)
        return 2
    from app.core import generations as G
    port = G.target('core', args.room)
    req = urllib.request.Request(f'http://127.0.0.1:{port}/api/v1/chat/internal/rooms/{args.room}/work-note',
                                 data=json.dumps({'text': text}).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            out = json.loads(r.read() or b'{}')
    except Exception as exc:   # noqa: BLE001
        print(f'作業中のダンに伝えられませんでした（{exc}）。受け口の報告に、作業の前提が変わることを書いてください', file=sys.stderr)
        return 1
    if out.get('delivered'):
        print('作業中のダンに伝えました')
    else:
        print('部屋のダンは今作業していません（伝える必要はありません）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
