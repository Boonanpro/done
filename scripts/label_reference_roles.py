"""Annotate the current inspected library by what each reference demonstrates.

These are retrieval facets, not restrictions on generation or editing. Existing
explicit labels are preserved. The actual footage beneath a caption study does
not make that study a second cinematic-scene reference.
"""
import json,uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def reference_role(row):
    key=row['id'];family=row['family']
    if 'caption' in family or key=='dan-optical-type':return 'text'
    if key.startswith(('film-','stock-')) or key in ('mdn-flower','samplelib-road'):return 'scene'
    if 'diagram' in family or any(w in key for w in ('map','data-chart','flowchart','money-count')):return 'data'
    if key.startswith(('hf-code-','hf-ui-','hf-app-','hf-ios','hf-liquid-glass','hf-macos','hf-reddit','hf-spotify','hf-x-post','hf-yt-','hf-instagram')):return 'interface'
    if key.startswith('hf-'):return 'motion'
    return 'character'

if __name__=='__main__':
    for name in ('reference-library.json','component-library.json'):
        path=ROOT/'docs'/name
        rows=json.loads(path.read_text(encoding='utf8'))
        for row in rows:row.setdefault('reference_role',reference_role(row))
        temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        temp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
        temp.replace(path)
        print(name,len(rows))
