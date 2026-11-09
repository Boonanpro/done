"""本人の動画への指摘を記録し、編集の手順書（talking-demo-editing）を育てる（app/services/video_learning.py）。

  python scripts/video_learning.py pending  [--room <部屋>]          前の動画の後の、扱いがまだの本人の発言
  python scripts/video_learning.py record   [--room <部屋>] --feedback <id> … [--other <id> …] [--rest-other]
                                            --applied "<全編のどこに同じ決まりを当てはめたか>" [--video "<版>"]
  python scripts/video_learning.py evidence --job <id> --output <JSON>    学習の仕事が読む証拠
  python scripts/video_learning.py complete --job <id> --report <JSON>    学習の仕事の報告書を確かめて終える
  python scripts/video_learning.py status

--room を省くと、この部屋（環境変数 DAN_ROOM_ID）。
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import video_learning as V  # noqa: E402


def _room(value):
    room = value or os.environ.get('DAN_ROOM_ID')
    if not room:
        raise SystemExit('--room か DAN_ROOM_ID が要る')
    return room


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='action', required=True)
    s = sub.add_parser('pending'); s.add_argument('--room')
    s = sub.add_parser('record'); s.add_argument('--room')
    s.add_argument('--feedback', nargs='*', default=[]); s.add_argument('--other', nargs='*', default=[])
    s.add_argument('--rest-other', action='store_true'); s.add_argument('--applied', default=''); s.add_argument('--video', default='')
    s = sub.add_parser('evidence'); s.add_argument('--job', required=True); s.add_argument('--output', required=True)
    s = sub.add_parser('complete'); s.add_argument('--job', required=True); s.add_argument('--report', required=True)
    sub.add_parser('status')
    a = p.parse_args(argv)
    if a.action == 'pending':
        rows = V.pending(_room(a.room))
        for m in rows:
            text = ' '.join((m.get('content') or '').split())
            print(f"{m['id']}  {m.get('created_at', '')[:16]}  {text[:160]}")
        print(f'[video_learning] pending={len(rows)}')
    elif a.action == 'record':
        out = V.record(_room(a.room), a.feedback, a.other, a.applied, a.video, a.rest_other)
        print(json.dumps(out, ensure_ascii=False))
        if out['still_open']:
            print('[video_learning] まだ扱いの決まっていない発言があります: ' + ' '.join(out['still_open']))
    elif a.action == 'evidence':
        out = Path(a.output)
        out.write_text(json.dumps(V.evidence(a.job), ensure_ascii=False, indent=1), encoding='utf-8')
        out.chmod(0o600)
        print(out)
    elif a.action == 'complete':
        print(json.dumps(V.complete(a.job, json.loads(Path(a.report).read_text(encoding='utf-8'))), ensure_ascii=False))
    else:
        print(json.dumps(V.status(), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
