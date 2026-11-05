"""The customer's copy of a working Google Doc (see app/services/gdoc_client.py).

  deliver --work <作業用ID> [--client <お客さん用ID>] [--name <新しく作る時の名前>]
          [--allow-pending] [--force] [--dry-run <出力DOCX>]
  status  --client <お客さん用ID>
  adopt   --work <作業用ID> --client <前からあるお客さん用ID>
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import gdoc_client as C


def main():
    p = argparse.ArgumentParser(); sub = p.add_subparsers(dest='action', required=True)
    d = sub.add_parser('deliver')
    d.add_argument('--work', required=True); d.add_argument('--client'); d.add_argument('--name')
    d.add_argument('--account', default='shub6923'); d.add_argument('--author', default='株式会社パイナ')
    d.add_argument('--allow-pending', action='store_true', help='作業用に残る提案を除いて、確定した本文だけを渡す')
    d.add_argument('--force', action='store_true', help='お客さんの直し・コメントを取り込み済みの時だけ')
    d.add_argument('--dry-run', metavar='DOCX')
    s = sub.add_parser('status'); s.add_argument('--client', required=True); s.add_argument('--account', default='shub6923')
    t = sub.add_parser('adopt', help='前からあるお客さん用を引き継ぐ（今の中身を「前回渡した版」にする）')
    t.add_argument('--work', required=True); t.add_argument('--client', required=True); t.add_argument('--account', default='shub6923')
    a = p.parse_args()
    if a.action == 'adopt':
        print(json.dumps(C.adopt(a.account, a.work, a.client), ensure_ascii=False)); return
    if a.action == 'status':
        print(json.dumps(C.status(a.account, a.client), ensure_ascii=False, indent=1)); return
    if not a.client and not a.name: raise SystemExit('--name is required for a new customer copy')
    result = C.deliver(a.account, a.work, a.client, a.name, a.author, a.allow_pending, a.force, bool(a.dry_run))
    if a.dry_run:
        Path(a.dry_run).write_bytes(result.pop('output'))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
