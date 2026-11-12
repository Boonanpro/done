"""本人の動画への指摘を記録し、編集の手順書（talking-demo-editing）を育てる（app/services/video_learning.py）。

  python scripts/video_learning.py pending  [--room <部屋>]          前の動画の後の、扱いがまだの本人の発言
  python scripts/video_learning.py record   [--room <部屋>] --feedback <id> … [--other <id> …] [--rest-other]
                                            --applied "<全編のどこに同じ決まりを当てはめたか>" [--video "<版>"]
  python scripts/video_learning.py record   … --direction <id …>     作る前の指示・参考（参考動画・サムネの見本）
  python scripts/video_learning.py sweep    --room <部屋>             エディターの部屋の本人の言葉を裏で仕分けて記録
  python scripts/video_learning.py evidence --job <id> --output <JSON>    学習の仕事が読む証拠
  python scripts/video_learning.py complete --job <id> --report <JSON>    学習の仕事の報告書を確かめて終える
  python scripts/video_learning.py status

--room を省くと、この部屋（video_learning.room_from_env）。
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import video_learning as V  # noqa: E402


def _room(value):
    room = value or V.room_from_env()
    if not room:
        raise SystemExit('--room が要る（この番の部屋が分からない）')
    return room


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='action', required=True)
    s = sub.add_parser('pending'); s.add_argument('--room')
    s = sub.add_parser('record'); s.add_argument('--room')
    s.add_argument('--feedback', nargs='*', default=[]); s.add_argument('--other', nargs='*', default=[])
    s.add_argument('--direction', nargs='*', default=[])
    s.add_argument('--rest-other', action='store_true'); s.add_argument('--applied', default=''); s.add_argument('--video', default='')
    s = sub.add_parser('sweep'); s.add_argument('--room', required=True)
    s = sub.add_parser('evidence'); s.add_argument('--job', required=True); s.add_argument('--output', required=True)
    s = sub.add_parser('complete'); s.add_argument('--job', required=True); s.add_argument('--report', required=True)
    sub.add_parser('status')
    a = p.parse_args(argv)
    if a.action == 'pending':
        rows = V.pending(_room(a.room), before_first=True)
        for m in rows:
            text = ' '.join((m.get('content') or '').split())
            print(f"{m['id']}  {m.get('created_at', '')[:16]}  {text[:160]}")
        print(f'[video_learning] pending={len(rows)}')
    elif a.action == 'record':
        out = V.record(_room(a.room), a.feedback, a.other, a.applied, a.video, a.rest_other, direction=a.direction)
        print(json.dumps(out, ensure_ascii=False))
        if out['still_open']:
            print('[video_learning] まだ扱いの決まっていない発言があります: ' + ' '.join(out['still_open']))
    elif a.action == 'sweep':
        from datetime import datetime
        try:
            out = V.sweep(a.room)
        except Exception as exc:  # noqa: BLE001 — 次のターンの終わりにまた試す
            out = {'error': f'{type(exc).__name__}: {exc}'}
        print(datetime.now().isoformat(timespec='seconds'), a.room[:8], json.dumps(out, ensure_ascii=False), flush=True)
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
