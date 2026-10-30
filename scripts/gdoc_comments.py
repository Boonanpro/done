"""Local administration / authorized reply helper for push-only Docs comments."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import gdoc_events as E

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='action', required=True)
    r = sub.add_parser('register'); r.add_argument('--file', required=True); r.add_argument('--room', required=True); r.add_argument('--account', required=True)
    r = sub.add_parser('reply'); r.add_argument('--batch', required=True); r.add_argument('--comment', required=True); r.add_argument('--text-file', required=True)
    r = sub.add_parser('history'); r.add_argument('--room', required=True)
    for name in ('pause', 'resume'):
        r = sub.add_parser(name); r.add_argument('--file', required=True)
    sub.add_parser('status')
    a = p.parse_args()
    if a.action=='register': E.register(a.file, a.room, a.account); print('Registered')
    elif a.action=='reply': print(json.dumps(E.reply(a.batch, a.comment, Path(a.text_file).read_text()), ensure_ascii=False))
    elif a.action=='history': print(E.room_context(a.room))
    elif a.action in ('pause','resume'):
        with E.db() as c:
            c.execute('UPDATE docs SET failures=?,retry_at=0,error=? WHERE file_id=?',
                      (3 if a.action=='pause' else 0, 'Paused' if a.action=='pause' else None, a.file))
        E.signal(); print(a.action)
    else:
        with E.db() as c:
            print(json.dumps({'documents':[dict(x) for x in c.execute('SELECT * FROM docs')],
                              'batches':[dict(x) for x in c.execute('SELECT id,file_id,status,created FROM batches')]}, ensure_ascii=False))

if __name__=='__main__': main()
