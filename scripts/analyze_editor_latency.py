"""Measure editor worker wall time and tool intervals from existing audit files.
Overlapping tools are counted once; the residual is unattributed, not 'thinking'.
"""
import argparse,json
from datetime import datetime
from pathlib import Path


def timestamp(row):
    return datetime.fromisoformat(row['created_at']).timestamp()


def summarize(folder):
    events=[json.loads(line) for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines() if line]
    start=timestamp(events[0]);end=timestamp(events[-1])
    intervals=[];pending={};tools=[]
    for row in events:
        if row.get('type')!='tool_progress':continue
        key=row.get('id');now=timestamp(row)
        if row.get('state')=='running':pending[key]=(now,row.get('name',''))
        elif key in pending:
            began,name=pending.pop(key)
            intervals.append((began,now));tools.append({'name':name,'start_seconds':round(began-start,3),'duration_seconds':round(now-began,3),'state':row['state']})
    merged=[]
    for a,b in sorted(intervals):
        if merged and a<=merged[-1][1]:merged[-1][1]=max(b,merged[-1][1])
        else:merged.append([a,b])
    occupied=sum(b-a for a,b in merged)
    return {'job_id':folder.name,'worker_seconds':round(end-start,3),
        'tool_union_seconds':round(occupied,3),'outside_recorded_tools_seconds':round(end-start-occupied,3),
        'first_text_seconds':next((round(timestamp(r)-start,3) for r in events if r.get('type')=='text'),None),
        'tools':tools,'unfinished_tool_ids':list(pending),
        'note':'Outside-tool time includes model requests, startup, streaming and orchestration; these logs do not separate them. Tool completion does not establish native window display or speaker playback completion.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('job_folder',type=Path);p.add_argument('--output',type=Path);args=p.parse_args()
    result=summarize(args.job_folder);encoded=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:args.output.write_text(encoded,encoding='utf-8')
    print(encoded)
