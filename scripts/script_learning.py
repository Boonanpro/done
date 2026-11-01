"""Enable collection, inspect evidence, and validate learning-job completion."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services import gdoc_events as E, script_learning as L


def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='action',required=True)
    for name in ('enable','capture','before','after','pause','resume'):
        s=sub.add_parser(name);s.add_argument('--file',required=True)
    s=sub.add_parser('evidence');s.add_argument('--job',required=True);s.add_argument('--output',required=True)
    s=sub.add_parser('complete');s.add_argument('--job',required=True);s.add_argument('--report',required=True)
    sub.add_parser('status')
    a=p.parse_args()
    if a.action=='evidence':
        out=Path(a.output);out.write_text(json.dumps(L.evidence(a.job),ensure_ascii=False,indent=2));out.chmod(0o600)
        print(str(out));return
    if a.action=='complete':L.complete(a.job,json.loads(Path(a.report).read_text()));print('Report validated');return
    if a.action=='status':
        with L.db() as c:
            result={k:[dict(r) for r in c.execute('SELECT * FROM '+k)] for k in ('targets','jobs')}
            result['snapshots']=[dict(r) for r in c.execute('SELECT file_id,count(*) AS count FROM snapshots GROUP BY file_id')]
        print(json.dumps(result,ensure_ascii=False));return
    with E.db() as c: row=c.execute('SELECT * FROM docs WHERE file_id=?',(a.file,)).fetchone()
    if not row:raise ValueError('Register document with gdoc_comments first')
    doc=dict(row)
    if a.action=='enable':result=L.enable(doc)
    elif a.action=='capture':result=L.capture(doc)
    elif a.action in ('before','after'):result=L.edit_boundary(doc,a.action)
    else:
        with L.db() as c:
            c.execute('UPDATE targets SET enabled=?,failures=0,due=0,error=NULL WHERE file_id=?',(int(a.action=='resume'),a.file))
        E.signal();result={'state':a.action}
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
